"""Staged official HTTP entry; preserve the qualified transport and solver core."""
import bridge_runtime
import table_http_feedback

core = bridge_runtime.core
table_http_feedback.BRIDGE = bridge_runtime
core.map_feedback = table_http_feedback.feedback

if __name__ == '__main__':
    bridge_runtime.verify_package()
    core.main()
