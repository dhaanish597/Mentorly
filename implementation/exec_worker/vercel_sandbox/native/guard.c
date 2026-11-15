/* Exact-version native return/trace boundary. No Python-held signing key.
 * OS resource/mount/network controls remain the external supervisor's job.
 */
#define _GNU_SOURCE
#define PY_SSIZE_T_CLEAN
#include <Python.h>
#include <frameobject.h>
#include <openssl/crypto.h>
#include <openssl/evp.h>
#include <openssl/hmac.h>
#include <openssl/sha.h>
#include <linux/audit.h>
#include <linux/filter.h>
#include <linux/seccomp.h>
#include <sys/prctl.h>
#include <sys/syscall.h>
#include <sys/mman.h>
#include <sys/uio.h>
#include <sched.h>
#include <unistd.h>
#include <errno.h>
#include <stddef.h>
#include <stdint.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <math.h>

#if PY_MAJOR_VERSION != 3 || PY_MINOR_VERSION != 14 || PY_MICRO_VERSION != 4
#error Exact CPython 3.14.4 headers are required
#endif
#if defined(Py_GIL_DISABLED) || defined(Py_DEBUG) || !defined(__x86_64__)
#error Only GIL-enabled non-debug Linux x86_64 is supported
#endif
#ifndef VIVA_BUILD_SOABI
#error Build must bind SOABI
#endif

#define BODY_CAP 262144
#define INPUT_CAP 262144
#define CODE_CAP 4096
#define FRAME_CAP 1024
#define POLICY_VERSION "native-boundary-v1"

typedef struct { char *p; size_t len, cap; int full; } Buffer;
typedef struct { PyObject *object, *names; int names_truncated; } Code;
typedef struct { PyFrameObject *frame; Code *code; unsigned id, parent, depth; int pending; } Frame;
static int started, active, tracing, tampered, truncated, installing_trace;
static pid_t owner_pid;
static long owner_tid;
static unsigned char signing_key[32];
static char input_hash[65], source_hash[65];
static PyObject *root_code;
static Code codes[CODE_CAP];
static size_t code_count, frame_count;
static Frame frames[FRAME_CAP];
static unsigned long long observed;
static size_t recorded, max_steps = 250, work_left = 2000;
static Buffer trace;
static int frames_sealed;
static PyGetSetDef guarded_frame_fields[5];

static PyObject *guarded_frame_get(PyObject *frame, void *closure) {
    PyObject *original = (PyObject *)closure;
    return Py_TYPE(original)->tp_descr_get(original, frame, (PyObject *)&PyFrame_Type);
}
static int guarded_frame_set(PyObject *frame, PyObject *value, void *closure) {
    (void)frame; (void)value; (void)closure;
    if (active && tracing) tampered = 1;
    PyErr_SetString(PyExc_PermissionError, "Frame trace state is immutable under native execution");
    return -1;
}
static int seal_frames(void) {
    if (frames_sealed) return 0;
    const char *names[] = {"f_trace", "f_trace_lines", "f_trace_opcodes", "f_lineno"};
    for (size_t i = 0; i < 4; i++) {
        PyObject *original = PyDict_GetItemString(PyFrame_Type.tp_dict, names[i]);
        if (!original || !Py_TYPE(original)->tp_descr_get) return -1;
        guarded_frame_fields[i].name = (char *)names[i];
        guarded_frame_fields[i].get = guarded_frame_get;
        guarded_frame_fields[i].set = guarded_frame_set;
        guarded_frame_fields[i].doc = "Native execution trace state";
        guarded_frame_fields[i].closure = Py_NewRef(original); /* Private C reference. */
        PyObject *replacement = PyDescr_NewGetSet(&PyFrame_Type, &guarded_frame_fields[i]);
        if (!replacement || PyDict_SetItemString(PyFrame_Type.tp_dict, names[i], replacement)) { Py_XDECREF(replacement); return -1; }
        Py_DECREF(replacement);
    }
    PyType_Modified(&PyFrame_Type);
    frames_sealed = 1;
    return 0;
}

static void addn(Buffer *b, const char *s, size_t n) {
    if (b->full || n > b->cap - b->len) { b->full = 1; return; }
    memcpy(b->p + b->len, s, n); b->len += n;
}
static void add(Buffer *b, const char *s) { addn(b, s, strlen(s)); }
static void number(Buffer *b, long long n) { char s[48]; int k = snprintf(s, sizeof s, "%lld", n); if (k > 0) addn(b, s, (size_t)k); }
static void quoted_c(Buffer *b, const char *s, size_t limit) {
    add(b, "\"");
    for (size_t i = 0; s[i] && i < limit; i++) {
        unsigned char c = (unsigned char)s[i];
        if (c == '"' || c == '\\') { char escaped[2] = {'\\', (char)c}; addn(b, escaped, 2); }
        else if (c < 32 || c >= 127) { char escaped[7]; snprintf(escaped, sizeof escaped, "\\u%04x", c); add(b, escaped); }
        else addn(b, (const char *)&c, 1);
    }
    add(b, "\"");
}
static int quoted_py(Buffer *b, PyObject *s, Py_ssize_t limit) {
    if (!PyUnicode_CheckExact(s) || PyUnicode_GET_LENGTH(s) > limit) return 0;
    add(b, "\"");
    for (Py_ssize_t i = 0; i < PyUnicode_GET_LENGTH(s); i++) {
        Py_UCS4 c = PyUnicode_ReadChar(s, i);
        if (c == (Py_UCS4)-1 && PyErr_Occurred()) return 0;
        if (c == '"' || c == '\\') { char e[2] = {'\\', (char)c}; addn(b, e, 2); }
        else if (c >= 32 && c < 127) { char v = (char)c; addn(b, &v, 1); }
        else if (c <= 0xffff) { char e[7]; snprintf(e, sizeof e, "\\u%04x", (unsigned)c); add(b, e); }
        else { char e[13]; c -= 0x10000; snprintf(e, sizeof e, "\\u%04x\\u%04x", (unsigned)(0xd800 + (c >> 10)), (unsigned)(0xdc00 + (c & 1023))); add(b, e); }
    }
    add(b, "\""); return !b->full;
}
static int scalar(Buffer *b, PyObject *v) {
    if (v == Py_True || v == Py_False) { add(b, v == Py_True ? "true" : "false"); return 1; }
    if (PyLong_CheckExact(v)) {
        int overflow = 0; long long n = PyLong_AsLongLongAndOverflow(v, &overflow);
        if (overflow || PyErr_Occurred() || n < -9007199254740991LL || n > 9007199254740991LL) { PyErr_Clear(); return 0; }
        number(b, n); return 1;
    }
    if (PyUnicode_CheckExact(v)) return quoted_py(b, v, 256);
    return 0;
}
static int result_value(Buffer *b, PyObject *v) {
    if (scalar(b, v)) return 1;
    if (!PyList_CheckExact(v) || PyList_GET_SIZE(v) > 128) return 0;
    add(b, "[");
    for (Py_ssize_t i = 0; i < PyList_GET_SIZE(v); i++) { if (i) add(b, ","); if (!scalar(b, PyList_GET_ITEM(v, i))) return 0; }
    add(b, "]"); return !b->full;
}
static void snapshot(Buffer *b, PyObject *v, int depth) {
    if (!work_left || depth > 3) { truncated = 1; add(b, "\"[truncated]\""); return; }
    work_left--;
    if (v == Py_None) { add(b, "null"); return; }
    size_t old = b->len;
    if (scalar(b, v)) return;
    b->len = old; PyErr_Clear();
    if (PyFloat_CheckExact(v)) {
        double d = PyFloat_AS_DOUBLE(v);
        if (isfinite(d)) { char s[64]; snprintf(s, sizeof s, "%.17g", d); add(b, s); return; }
    }
    if (PyList_CheckExact(v) || PyTuple_CheckExact(v)) {
        Py_ssize_t n = PyList_CheckExact(v) ? PyList_GET_SIZE(v) : PyTuple_GET_SIZE(v);
        add(b, "[");
        for (Py_ssize_t i = 0; i < n && i < 20; i++) { if (i) add(b, ","); snapshot(b, PyList_CheckExact(v) ? PyList_GET_ITEM(v, i) : PyTuple_GET_ITEM(v, i), depth + 1); }
        if (n > 20) { truncated = 1; if (n) add(b, ","); add(b, "\"[truncated]\""); }
        add(b, "]"); return;
    }
    if (PyDict_CheckExact(v)) {
        Py_ssize_t pos = 0; PyObject *key, *value; int count = 0;
        add(b, "{");
        while (count < 20 && work_left && PyDict_Next(v, &pos, &key, &value)) {
            work_left--;
            if (!PyUnicode_CheckExact(key) || PyUnicode_GET_LENGTH(key) > 128) continue;
            if (count++) add(b, ","); quoted_py(b, key, 128); add(b, ":"); snapshot(b, value, depth + 1);
        }
        if (PyDict_Size(v) > count) truncated = 1;
        add(b, "}"); return;
    }
    quoted_c(b, Py_TYPE(v)->tp_name, 128);
}
static int owned(void) { return getpid() == owner_pid && syscall(SYS_gettid) == owner_tid; }
static int deny(const char *event, PyObject *args, void *unused) {
    (void)unused;
    if (!active) return 0;
    if (installing_trace && owned() && (!strcmp(event, "sys.settrace") || !strcmp(event, "sys.monitoring.register_callback"))) return 0;
    int forbidden = !strncmp(event, "ctypes.", 7) || !strncmp(event, "marshal.", 8)
        || !strncmp(event, "gc.get_", 7) || !strncmp(event, "subprocess.", 11)
        || !strcmp(event, "code.__new__") || !strcmp(event, "function.__new__")
        || !strcmp(event, "sys._getframe") || !strcmp(event, "sys._current_frames")
        || !strcmp(event, "sys._current_exceptions") || !strcmp(event, "sys.settrace")
        || !strcmp(event, "sys.setprofile") || !strcmp(event, "sys.addaudithook")
        || !strncmp(event, "sys.monitoring.", 15)
        || !strcmp(event, "mmap.__new__") || !strncmp(event, "os.exec", 7)
        || !strncmp(event, "os.posix_spawn", 14) || !strcmp(event, "pickle.find_class");
    if (!strcmp(event, "object.__getattr__") || !strcmp(event, "object.__setattr__")) {
        if (PyTuple_Check(args) && PyTuple_GET_SIZE(args) >= 2) {
            PyObject *name = PyTuple_GET_ITEM(args, 1);
            if (PyUnicode_Check(name)) {
                const char *s = PyUnicode_AsUTF8(name);
                if (s && (!strcmp(s, "f_code") || !strcmp(s, "tb_frame") || !strcmp(s, "gi_frame")
                    || !strcmp(s, "cr_frame") || !strcmp(s, "ag_frame") || !strcmp(s, "__code__")
                    || !strcmp(s, "gi_code") || !strcmp(s, "cr_code") || !strcmp(s, "ag_code")
                    || !strcmp(s, "f_trace"))) forbidden = 1;
            }
        }
    }
    if (!strcmp(event, "import") && PyTuple_Check(args) && PyTuple_GET_SIZE(args) >= 2) {
        PyObject *name = PyTuple_GET_ITEM(args, 0), *path = PyTuple_GET_ITEM(args, 1);
        const char *n = PyUnicode_Check(name) ? PyUnicode_AsUTF8(name) : NULL;
        if (n && (!strncmp(n, "_ctypes", 7) || !strncmp(n, "_test", 5) || !strncmp(n, "_interpreters", 13)
                  || !strncmp(n, "_xxsubinterpreters", 18) || !strcmp(n, "ctypes"))) forbidden = 1;
        if (PyUnicode_Check(path)) forbidden = 1; /* All later native loads, including subclass aliases. */
    }
    if (tracing && (!strcmp(event, "compile") || !strcmp(event, "exec"))) tampered = 1;
    if (forbidden) { if (tracing) tampered = 1; PyErr_SetString(PyExc_PermissionError, "Operation denied by native execution policy"); return -1; }
    return 0;
}

#define REJECT_SYSCALL(n) BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, (n), 0, 1), BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM)
static int seccomp_policy(void) {
    struct sock_filter f[] = {
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, arch)),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, AUDIT_ARCH_X86_64, 1, 0),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, nr)),
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, 0x40000000, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_KILL_PROCESS),
        REJECT_SYSCALL(SYS_ptrace), REJECT_SYSCALL(SYS_process_vm_readv), REJECT_SYSCALL(SYS_process_vm_writev),
        REJECT_SYSCALL(SYS_execve), REJECT_SYSCALL(SYS_execveat), REJECT_SYSCALL(SYS_memfd_create),
        REJECT_SYSCALL(SYS_pidfd_getfd), REJECT_SYSCALL(SYS_open_by_handle_at), REJECT_SYSCALL(SYS_bpf),
        REJECT_SYSCALL(SYS_perf_event_open), REJECT_SYSCALL(SYS_userfaultfd), REJECT_SYSCALL(SYS_pkey_mprotect),
        REJECT_SYSCALL(SYS_io_uring_setup), REJECT_SYSCALL(SYS_io_uring_enter), REJECT_SYSCALL(SYS_io_uring_register),
        REJECT_SYSCALL(SYS_rt_sigaction),
        REJECT_SYSCALL(SYS_shmat), REJECT_SYSCALL(SYS_shmget), REJECT_SYSCALL(SYS_personality),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_clone3, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|ENOSYS),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_clone, 0, 4),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[0])),
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, CLONE_VM|CLONE_THREAD, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_mmap, 1, 0),
        BPF_JUMP(BPF_JMP|BPF_JEQ|BPF_K, SYS_mprotect, 0, 4),
        BPF_STMT(BPF_LD|BPF_W|BPF_ABS, offsetof(struct seccomp_data, args[2])),
        BPF_JUMP(BPF_JMP|BPF_JSET|BPF_K, PROT_EXEC, 0, 1),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ERRNO|EPERM),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW),
        BPF_STMT(BPF_RET|BPF_K, SECCOMP_RET_ALLOW)
    };
    struct sock_fprog p = {(unsigned short)(sizeof f / sizeof f[0]), f};
    return prctl(PR_SET_NO_NEW_PRIVS, 1, 0, 0, 0) || prctl(PR_SET_SECCOMP, SECCOMP_MODE_FILTER, &p);
}
static int native_policy_test(void) {
    int probe = 37, copy = 0;
    struct iovec local = {&copy, sizeof copy}, remote = {&probe, sizeof probe};
    errno = 0;
    if (syscall(SYS_process_vm_readv, getpid(), &local, 1, &remote, 1, 0) != -1 || errno != EPERM) return -1;
    local.iov_base = &probe; remote.iov_base = &copy;
    errno = 0;
    if (syscall(SYS_process_vm_writev, getpid(), &local, 1, &remote, 1, 0) != -1 || errno != EPERM) return -1;
    void *page = mmap(NULL, 4096, PROT_READ|PROT_WRITE, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    if (page == MAP_FAILED) return -1;
    errno = 0; int protected = mprotect(page, 4096, PROT_READ|PROT_EXEC);
    int protection_errno = errno; munmap(page, 4096);
    if (protected != -1 || protection_errno != EPERM) return -1;
    errno = 0; page = mmap(NULL, 4096, PROT_READ|PROT_EXEC, MAP_PRIVATE|MAP_ANONYMOUS, -1, 0);
    if (page != MAP_FAILED) { munmap(page, 4096); return -1; }
    return errno == EPERM && prctl(PR_GET_SECCOMP, 0, 0, 0, 0) == 2 ? 0 : -1;
}
static int collect_codes(PyObject *code) {
    if (code_count == CODE_CAP) return -1;
    Code *entry = &codes[code_count++]; entry->object = Py_NewRef(code);
    PyObject *declared[] = {PyCode_GetVarnames((PyCodeObject *)code), PyCode_GetCellvars((PyCodeObject *)code), PyCode_GetFreevars((PyCodeObject *)code)};
    PyObject *names = PyList_New(0), *seen = PySet_New(NULL);
    if (!names || !seen) return -1;
    for (size_t group = 0; group < 3; group++) {
        if (!declared[group] || !PyTuple_CheckExact(declared[group])) return -1;
        for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(declared[group]); i++) {
            PyObject *name = PyTuple_GET_ITEM(declared[group], i);
            if (!PyUnicode_CheckExact(name)) continue;
            int present = PySet_Contains(seen, name); if (present < 0) return -1; if (present) continue;
            if (PyList_GET_SIZE(names) >= 128) { entry->names_truncated = 1; break; }
            if (PySet_Add(seen, name) || PyList_Append(names, name)) return -1;
        }
        Py_DECREF(declared[group]);
    }
    entry->names = PyList_AsTuple(names); Py_DECREF(names); Py_DECREF(seen); if (!entry->names) return -1;
    PyObject *constants = PyObject_GetAttrString(code, "co_consts");
    if (!constants || !PyTuple_CheckExact(constants)) { Py_XDECREF(constants); return -1; }
    for (Py_ssize_t i = 0; i < PyTuple_GET_SIZE(constants); i++) {
        PyObject *v = PyTuple_GET_ITEM(constants, i);
        if (PyCode_Check(v) && collect_codes(v)) { Py_DECREF(constants); return -1; }
    }
    Py_DECREF(constants); return 0;
}
static Code *source_code(PyObject *code) { for (size_t i = 0; i < code_count; i++) if (codes[i].object == code) return &codes[i]; return NULL; }
static Frame *frame_entry(PyFrameObject *frame, Code *code) {
    for (size_t i = 0; i < frame_count; i++) if (frames[i].frame == frame) return &frames[i];
    if (frame_count == FRAME_CAP) { truncated = 1; return NULL; }
    Frame *f = &frames[frame_count]; f->frame = (PyFrameObject *)Py_NewRef((PyObject *)frame); f->code = code; f->id = (unsigned)++frame_count; f->depth = 1;
    PyFrameObject *back = PyFrame_GetBack(frame);
    for (size_t i = 0; back && i + 1 < frame_count; i++) if (frames[i].frame == back) { f->parent = frames[i].id; f->depth = frames[i].depth + 1; break; }
    Py_XDECREF(back); return f;
}
static void event(Frame *f, const char *kind, int line) {
    unsigned long long index = observed++;
    if (recorded >= max_steps || trace.full) { truncated = 1; return; }
    char local_storage[16384]; Buffer locals = {local_storage, 0, sizeof local_storage, 0};
    add(&locals, "{");
    int count = 0;
    Py_ssize_t name_count = PyTuple_GET_SIZE(f->code->names);
    if (f->code->names_truncated || name_count > 30) truncated = 1;
    for (Py_ssize_t i = 0; i < name_count && count < 30; i++) {
        if (!work_left) { truncated = 1; break; }
        work_left--;
        PyObject *key = PyTuple_GET_ITEM(f->code->names, i);
        if (!PyUnicode_CheckExact(key) || PyUnicode_GET_LENGTH(key) > 128) continue;
        const char *name = PyUnicode_AsUTF8(key);
        if (!name || !strncmp(name, "__", 2)) continue;
        PyObject *value = PyFrame_GetVar(f->frame, key);
        if (!value) { PyErr_Clear(); continue; }
        if (count++) add(&locals, ","); quoted_py(&locals, key, 128); add(&locals, ":"); snapshot(&locals, value, 0);
        Py_DECREF(value);
    }
    PyErr_Clear(); add(&locals, "}");
    char step_storage[18432]; Buffer step = {step_storage, 0, sizeof step_storage, 0};
    add(&step, "{\"event_id\":"); number(&step, (long long)index); add(&step, ",\"frame_id\":\"f"); number(&step, f->id);
    add(&step, "\",\"parent_frame_id\":");
    if (f->parent) { add(&step, "\"f"); number(&step, f->parent); add(&step, "\""); } else add(&step, "null");
    add(&step, ",\"call_depth\":"); number(&step, f->depth); add(&step, ",\"source_hash\":\""); add(&step, source_hash);
    add(&step, "\",\"source_line\":"); number(&step, line < 1 ? 1 : line); add(&step, ",\"event_kind\":"); quoted_c(&step, kind, 16);
    add(&step, ",\"attribution_status\":\"ATTRIBUTED\",\"locals_snapshot\":");
    if (locals.full) { add(&step, "{}"); truncated = 1; } else addn(&step, locals.p, locals.len);
    add(&step, ",\"truncated_values\":"); add(&step, truncated ? "[\"snapshot_budget\",\"dynamic_extra_locals_omitted\"]}" : "[\"dynamic_extra_locals_omitted\"]}");
    if (step.full || step.len + 1 > trace.cap - trace.len) { truncated = 1; return; }
    if (recorded++) add(&trace, ","); addn(&trace, step.p, step.len);
}
static int trace_event(PyObject *unused, PyFrameObject *frame, int what, PyObject *arg) {
    (void)unused; (void)arg;
    if (!owned()) { tampered = 1; return 0; }
    int gc_enabled = PyGC_Disable();
    PyObject *saved_exception = PyErr_GetRaisedException();
    PyCodeObject *code = PyFrame_GetCode(frame); Code *matched = code ? source_code((PyObject *)code) : NULL; Py_XDECREF(code);
    Frame *f = matched ? frame_entry(frame, matched) : NULL;
    if (f) {
        if (what == PyTrace_CALL) event(f, "CALL", PyFrame_GetLineNumber(frame));
        else if (what == PyTrace_LINE) { if (f->pending) event(f, "LINE", f->pending); f->pending = PyFrame_GetLineNumber(frame); }
        else if (what == PyTrace_RETURN || what == PyTrace_EXCEPTION) {
            if (f->pending) { event(f, "LINE", f->pending); f->pending = 0; }
            event(f, what == PyTrace_RETURN ? "RETURN" : "EXCEPTION", PyFrame_GetLineNumber(frame));
        }
    }
    PyErr_Clear(); if (gc_enabled) PyGC_Enable(); PyErr_SetRaisedException(saved_exception);
    return 0;
}
static int read_all(int fd, void *p, size_t count) {
    size_t used = 0; while (used < count) { ssize_t n = read(fd, (char *)p + used, count - used); if (n < 0 && errno == EINTR) continue; if (n <= 0) return -1; used += (size_t)n; } return 0;
}
static int write_all(int fd, const void *p, size_t count) {
    size_t used = 0; while (used < count) { ssize_t n = write(fd, (const char *)p + used, count - used); if (n < 0 && errno == EINTR) continue; if (n <= 0) return -1; used += (size_t)n; } return 0;
}
static void hex(const unsigned char *in, char *out) { for (size_t i = 0; i < 32; i++) { out[i*2] = "0123456789abcdef"[in[i] >> 4]; out[i*2+1] = "0123456789abcdef"[in[i] & 15]; } out[64] = 0; }
static int preload(void) {
    const char *names[] = {"math", "collections", "heapq", "bisect", "functools", "itertools", "operator", "typing", "random", "statistics", "decimal", "datetime", "fractions", "re", "json", "socket", "pathlib", "os", "errno", "time", "array", "copy", "struct", "hashlib", "select", "zlib", "unicodedata", "gc", "signal", NULL};
    for (size_t i = 0; names[i]; i++) { PyObject *m = PyImport_ImportModule(names[i]); if (!m) return -1; Py_DECREF(m); }
    return 0;
}
static PyObject *run(PyObject *module, PyObject *args) {
    (void)module;
    int key_fd, result_fd;
    if (started || !PyArg_ParseTuple(args, "ii", &key_fd, &result_fd) || key_fd < 3 || result_fd < 3 || key_fd == result_fd) { PyErr_SetString(PyExc_PermissionError, "Native invocation is one-shot"); return NULL; }
    started = 1; owner_pid = getpid(); owner_tid = syscall(SYS_gettid);
    if (strncmp(Py_GetVersion(), PY_VERSION " ", strlen(PY_VERSION) + 1) || preload()) _exit(111);
    PyObject *config = PyImport_ImportModule("sysconfig"), *abi = config ? PyObject_CallMethod(config, "get_config_var", "s", "SOABI") : NULL;
    if (!abi || !PyUnicode_CheckExact(abi) || strcmp(PyUnicode_AsUTF8(abi), VIVA_BUILD_SOABI)) _exit(111);
    Py_XDECREF(abi); Py_XDECREF(config);
    if (read_all(key_fd, signing_key, sizeof signing_key)) _exit(111);
    close(key_fd);
    FILE *input = fopen("/ipc/payload.json", "rb"); if (!input) _exit(111);
    char *raw = malloc(INPUT_CAP + 1); if (!raw) _exit(111);
    size_t n = fread(raw, 1, INPUT_CAP + 1, input); fclose(input); if (!n || n > INPUT_CAP) _exit(111); raw[n] = 0;
    unsigned char hash[32]; SHA256((unsigned char *)raw, n, hash); hex(hash, input_hash);
    PyObject *json = PyImport_ImportModule("json"), *payload = json ? PyObject_CallMethod(json, "loads", "s", raw) : NULL;
    free(raw); Py_XDECREF(json); if (!payload || !PyDict_CheckExact(payload)) _exit(111);
    PyObject *source = PyDict_GetItemString(payload, "source_code"), *name = PyDict_GetItemString(payload, "function_name"), *kwargs = PyDict_GetItemString(payload, "input_args"), *mode = PyDict_GetItemString(payload, "mode"), *bound = PyDict_GetItemString(payload, "source_hash"), *budget = PyDict_GetItemString(payload, "budget");
    if (!source || !PyUnicode_CheckExact(source) || !name || !PyUnicode_CheckExact(name) || !kwargs || !PyDict_CheckExact(kwargs) || !mode || !PyUnicode_CheckExact(mode) || !bound || !PyUnicode_CheckExact(bound) || !budget || !PyDict_CheckExact(budget)) _exit(111);
    const char *mode_string = PyUnicode_AsUTF8(mode); int requested_trace = mode_string && !strcmp(mode_string, "trace");
    if (!mode_string || (!requested_trace && strcmp(mode_string, "execute"))) _exit(111);
    Py_ssize_t source_len; const char *text = PyUnicode_AsUTF8AndSize(source, &source_len);
    if (!text || memchr(text, 0, (size_t)source_len)) _exit(111);
    SHA256((const unsigned char *)text, (size_t)source_len, hash); hex(hash, source_hash);
    const char *bound_hash = PyUnicode_AsUTF8(bound);
    if (!bound_hash || strcmp(source_hash, bound_hash)) _exit(111);
    char *immutable_source = malloc((size_t)source_len + 1); if (!immutable_source) _exit(111); memcpy(immutable_source, text, (size_t)source_len + 1);
    char *function_name = strdup(PyUnicode_AsUTF8(name)); if (!function_name) _exit(111);
    PyObject *steps = PyDict_GetItemString(budget, "max_trace_steps"), *work = PyDict_GetItemString(budget, "max_trace_snapshots_work");
    if (!steps || !PyLong_CheckExact(steps) || !work || !PyLong_CheckExact(work)) _exit(111);
    max_steps = PyLong_AsUnsignedLong(steps); work_left = PyLong_AsUnsignedLong(work); if (PyErr_Occurred() || !max_steps || max_steps > 250 || !work_left || work_left > 2000) _exit(111);
    trace.p = calloc(1, BODY_CAP); trace.cap = BODY_CAP - 16384; if (!trace.p) _exit(111);
    root_code = Py_CompileString(immutable_source, "<learner>", Py_file_input); free(immutable_source);
    PyObject *compile_exception = root_code ? NULL : PyErr_GetRaisedException();
    if (root_code && collect_codes(root_code)) _exit(111);
    if (PySys_AddAuditHook(deny, NULL) || seccomp_policy() || native_policy_test()) _exit(111);
    active = 1; tracing = requested_trace;
    PyObject *namespace = PyDict_New(), *builtins = PyEval_GetBuiltins();
    if (!namespace || PyDict_SetItemString(namespace, "__builtins__", builtins)) _exit(111);
    struct timespec begin, end; clock_gettime(CLOCK_MONOTONIC, &begin);
    if (compile_exception) PyErr_SetRaisedException(compile_exception);
    PyObject *loaded = root_code ? PyEval_EvalCode(root_code, namespace, namespace) : NULL;
    PyObject *value = NULL;
    if (loaded) {
        Py_DECREF(loaded); PyObject *target = PyDict_GetItemString(namespace, function_name);
        if (!target || !PyCallable_Check(target)) PyErr_SetString(PyExc_AttributeError, "Required callable is missing");
        else {
            tracing = requested_trace;
            if (tracing) {
                int gc_enabled = PyGC_Disable();
                installing_trace = 1; PyEval_SetTrace(trace_event, Py_None); installing_trace = 0;
                if (PyThreadState_Get()->c_tracefunc != trace_event || PyThreadState_Get()->c_traceobj != Py_None) _exit(111);
                if (gc_enabled) PyGC_Enable();
            }
            PyObject *empty = PyTuple_New(0); value = empty ? PyObject_Call(target, empty, kwargs) : NULL;
            PyObject *call_exception = value ? NULL : PyErr_GetRaisedException();
            Py_XDECREF(empty);
            if (tracing) {
                int gc_enabled = PyGC_Disable();
                installing_trace = 1; PyEval_SetTrace(NULL, NULL); installing_trace = 0;
                if (PyThreadState_Get()->c_tracefunc != NULL) _exit(111);
                if (gc_enabled) PyGC_Enable();
            }
            if (call_exception) PyErr_SetRaisedException(call_exception);
        }
    }
    clock_gettime(CLOCK_MONOTONIC, &end);
    if (!owned()) _exit(113);
    PyObject *exception = value ? NULL : PyErr_GetRaisedException();
    char result_storage[65536]; Buffer result = {result_storage, 0, sizeof result_storage, 0};
    int valid = value && result_value(&result, value);
    PyErr_Clear();
    const char *kind = value ? (valid && !result.full ? "RETURN" : "INVALID_RESULT") : "EXCEPTION";
    const char *error = value ? (valid ? NULL : "InvalidReturnType") : (exception ? Py_TYPE(exception)->tp_name : "NativeInvocationError");
    char *body_storage = calloc(1, BODY_CAP); if (!body_storage) _exit(111);
    Buffer body = {body_storage, 0, BODY_CAP, 0};
    add(&body, "{\"protocol_version\":\"v1\",\"mode\":"); quoted_c(&body, requested_trace ? "trace" : "execute", 8); add(&body, ",\"kind\":"); quoted_c(&body, kind, 32);
    add(&body, ",\"return_value\":"); if (valid && !result.full) addn(&body, result.p, result.len); else add(&body, "null");
    add(&body, ",\"error_type\":"); if (error) quoted_c(&body, error, 128); else add(&body, "null");
    add(&body, ",\"error_message\":"); if (error) quoted_c(&body, value ? "Unsupported bounded return value" : "Learner raised an exception", 128); else add(&body, "null");
    add(&body, ",\"stdout_excerpt\":\"\",\"stderr_excerpt\":\"\",\"duration_ms\":");
    long long duration = (end.tv_sec - begin.tv_sec) * 1000LL + (end.tv_nsec - begin.tv_nsec) / 1000000LL; number(&body, duration < 0 ? 0 : duration);
    if (requested_trace) {
        add(&body, ",\"trace_status\":"); quoted_c(&body, tampered ? "TRACE_TAMPERED" : (truncated ? "PARTIAL" : (!recorded ? "TRACE_UNAVAILABLE" : "COMPLETED")), 32);
        add(&body, ",\"steps\":["); addn(&body, trace.p, trace.len); add(&body, "],\"total_observed\":"); number(&body, (long long)observed);
        add(&body, ",\"trace_truncated\":"); add(&body, truncated || tampered ? "true" : "false");
        add(&body, ",\"termination_reason\":"); quoted_c(&body, tampered ? "Native trace policy denied manipulation" : (truncated ? "Native trace bounds reached" : (!recorded ? "Requested callable has no submitted-source trace" : "Native trace completed; snapshots contain declared variables")), 128);
    }
    add(&body, "}"); if (body.full) _exit(111);
    const char prefix[] = "VIVA_NATIVE_V2";
    size_t authenticated_len = sizeof prefix + 65 + body.len; char *authenticated = malloc(authenticated_len); if (!authenticated) _exit(111);
    memcpy(authenticated, prefix, sizeof prefix); memcpy(authenticated + sizeof prefix, input_hash, 65); memcpy(authenticated + sizeof prefix + 65, body.p, body.len);
    unsigned char mac[32]; unsigned int mac_len;
    if (!HMAC(EVP_sha256(), signing_key, 32, (unsigned char *)authenticated, authenticated_len, mac, &mac_len) || mac_len != 32) _exit(111);
    OPENSSL_cleanse(signing_key, sizeof signing_key); active = 0; started = 1;
    char mac_hex[65], header[128]; hex(mac, mac_hex); int header_len = snprintf(header, sizeof header, "VIVA_NATIVE_V2 %s %zu\n", mac_hex, body.len);
    if (write_all(result_fd, header, (size_t)header_len) || write_all(result_fd, body.p, body.len)) _exit(112);
    _exit(0); /* No learner __del__, atexit or mutable Python envelope after signing. */
}
static PyMethodDef methods[] = {{"run", run, METH_VARARGS, "One-shot fixed-file native invocation."}, {NULL, NULL, 0, NULL}};
static struct PyModuleDef module = {PyModuleDef_HEAD_INIT, "_viva_native", NULL, -1, methods, NULL, NULL, NULL, NULL};
PyMODINIT_FUNC PyInit__viva_native(void) {
    if (seal_frames()) return NULL;
    PyObject *m = PyModule_Create(&module); if (!m) return NULL;
    if (PyModule_AddStringConstant(m, "build_python", PY_VERSION) || PyModule_AddStringConstant(m, "build_soabi", VIVA_BUILD_SOABI) || PyModule_AddStringConstant(m, "policy_version", POLICY_VERSION)) { Py_DECREF(m); return NULL; }
    return m;
}
