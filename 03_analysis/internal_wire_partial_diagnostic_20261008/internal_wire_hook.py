"""Optional declaration callback; original extraction and baseline are untouched."""
import internal_wire_repair


def configure(runtime, candidate, on_receipt):
    runtime.DECLARATION_REPAIR = None
    if candidate:
        def repair(code, feedback):
            patched, receipt = internal_wire_repair.repair(code, feedback)
            on_receipt(receipt)
            return patched
        runtime.DECLARATION_REPAIR = repair
