import type { FnSpec, Language, ParamType } from '@/lib/types'

export const LANGUAGES: { id: Language; label: string; monaco: string }[] = [
  { id: 'python', label: 'Python', monaco: 'python' },
  { id: 'cpp', label: 'C++', monaco: 'cpp' },
  { id: 'java', label: 'Java', monaco: 'java' },
  { id: 'c', label: 'C', monaco: 'c' },
]

const cppType: Record<ParamType, string> = { 'int[]': 'vector<int>&', int: 'int', string: 'string', bool: 'bool' }
const cppRet: Record<ParamType, string> = { 'int[]': 'vector<int>', int: 'int', string: 'string', bool: 'bool' }
const javaType: Record<ParamType, string> = { 'int[]': 'int[]', int: 'int', string: 'String', bool: 'boolean' }
const cType: Record<ParamType, string> = { 'int[]': 'int*', int: 'int', string: 'char*', bool: 'bool' }
const defaults: Record<ParamType, { cpp: string; java: string; c: string; py: string }> = {
  int: { cpp: '0', java: '0', c: '0', py: '0' },
  bool: { cpp: 'false', java: 'false', c: 'false', py: 'False' },
  string: { cpp: '""', java: '""', c: 'NULL', py: '""' },
  'int[]': { cpp: '{}', java: 'new int[0]', c: 'NULL', py: '[]' },
}

export function buildStarter(fn: FnSpec, lang: Language): string {
  const names = fn.params.map((p) => p.name)
  switch (lang) {
    case 'python':
      return `def ${fn.name}(${names.join(', ')}):\n    # Explain your approach to the mentor first, then write it here.\n    return ${defaults[fn.returns].py}\n`
    case 'cpp':
      return `#include <bits/stdc++.h>\nusing namespace std;\n\n${cppRet[fn.returns]} ${fn.name}(${fn.params.map((p) => `${cppType[p.type]} ${p.name}`).join(', ')}) {\n    // Explain your approach to the mentor first, then write it here.\n    return ${defaults[fn.returns].cpp};\n}\n`
    case 'java':
      return `class Solution {\n    public ${javaType[fn.returns]} ${fn.name}(${fn.params.map((p) => `${javaType[p.type]} ${p.name}`).join(', ')}) {\n        // Explain your approach to the mentor first, then write it here.\n        return ${defaults[fn.returns].java};\n    }\n}\n`
    case 'c': {
      const params = fn.params.flatMap((p) =>
        p.type === 'int[]' ? [`int* ${p.name}`, `int ${p.name}Size`] : [`${cType[p.type]} ${p.name}`],
      )
      return `#include <stdbool.h>\n#include <stdlib.h>\n\n${cType[fn.returns]} ${fn.name}(${params.join(', ')}) {\n    // Explain your approach to the mentor first, then write it here.\n    return ${defaults[fn.returns].c};\n}\n`
    }
  }
}
