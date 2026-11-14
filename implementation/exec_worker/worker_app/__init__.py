"""Voice Coding Coach Phase 1 (T-02) Execution Broker and Sandbox Worker Package."""

from .main import (
    ActiveJobRegistry,
    BrokerConfig,
    create_broker_app,
)
from .sandbox_runner import (
    DEFAULT_FRAME_PREFIX,
    DEFAULT_RUNNER_IMAGE,
    GVisorSandboxRunner,
    SandboxRunnerProtocol,
    SandboxRuntimePreflight,
    build_docker_run_command,
    check_runtime_preflight,
    parse_runner_frame,
)
from .verifier_harness import (
    generate_bounded_cases,
    run_verification_job,
)

__all__ = [
    "ActiveJobRegistry",
    "BrokerConfig",
    "DEFAULT_FRAME_PREFIX",
    "DEFAULT_RUNNER_IMAGE",
    "GVisorSandboxRunner",
    "SandboxRunnerProtocol",
    "SandboxRuntimePreflight",
    "build_docker_run_command",
    "check_runtime_preflight",
    "create_broker_app",
    "generate_bounded_cases",
    "parse_runner_frame",
    "run_verification_job",
]
