import json
from pathlib import Path
import test_parent_history
import test_parent_generation_binding
ROOT=Path(__file__).parent
test_parent_history.main()
test_parent_generation_binding.main()
read=lambda n:json.loads((ROOT/n).read_bytes())
result=dict(passed=True,worker=read('ACTUAL_PARENT_HISTORY_RESULT.json'),generation=read('ACTUAL_PARENT_GENERATION_RESULT.json'),new_real_model_EDA_FIFO_calls=0,score_or_adoption=False)
(ROOT/'ACTUAL_TABLE_HISTORY_CONTROLS_RESULT.json').write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result))
