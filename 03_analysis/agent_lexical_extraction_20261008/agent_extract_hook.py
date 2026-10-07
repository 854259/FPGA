"""Configure an agent-side callback; no baseline or prompt mutation."""
import agent_extract_boundary


def configure(runtime, candidate, on_receipt):
    runtime.RTL_EXTRACTOR = None
    if candidate:
        def extract(text, track, original_extract):
            code, receipt = agent_extract_boundary.extract_with_receipt(text, track, original_extract)
            on_receipt(receipt)
            return code
        runtime.RTL_EXTRACTOR = extract
