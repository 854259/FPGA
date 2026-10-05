import copy,json,unittest
from adapter import task_view,user_content,candidate_files,assembled_files,binding,safe_path,messages

def record():
    return dict(id='PRIVATE_ID',categories=['PRIVATE_CATEGORY'],input=dict(prompt='Design native_adder with the original ports.\n原文。',context={'rtl/native_adder.sv':'module native_adder(input a);\n// complete this\n','rtl/helper.sv':'module helper; endmodule\n','docs/spec.md':'Public context — keep exact.\n'}),output=dict(response='',context={'rtl/native_adder.sv':''}),harness={'files':{'rtl/reference.sv':'SECRET_REFERENCE','src/test.py':'SECRET_TEST'}})

G='你是 RTL 代码生成器。只输出一个完整、可综合的 Verilog/SystemVerilog `TopModule`，不要输出 Markdown、解释或测试台。\nKeep all original ports.\n'
REPAIR='Return complete TopModule, use actual diagnostics only.'

class Boundary(unittest.TestCase):
    def test_original_unicode_newline_context_roundtrip(self):
        r=record();v=task_view(r);d=json.loads(user_content(v));self.assertEqual(d['prompt'],r['input']['prompt']);self.assertEqual(d['context'],r['input']['context']);self.assertEqual(d['output_paths'],list(r['output']['context']))
    def test_hidden_harness_answers_ids_never_forwarded(self):
        r=record();content=user_content(task_view(r));self.assertNotIn('SECRET',content);self.assertNotIn('PRIVATE',content);changed=copy.deepcopy(r);changed['harness']['files']['src/test.py']='DIFFERENT_SECRET';changed['id']='OTHER_ID';self.assertEqual(task_view(changed),task_view(r))
    def test_public_context_change_is_bound(self):
        r=record();v=task_view(r);r['input']['context']['docs/spec.md']+='new';self.assertNotEqual(task_view(r),v)
        with self.assertRaises(ValueError):binding(r,v)
    def test_reference_in_output_rejected(self):
        for where in ['response','context']:
            r=record()
            if where=='response':r['output'][where]='SECRET_REFERENCE'
            else:r['output'][where]['rtl/native_adder.sv']='SECRET_REFERENCE'
            with self.assertRaises(ValueError):task_view(r)
    def test_path_traversal_absolute_normalized_and_platform_paths_rejected(self):
        for p in ['../x.sv','/x.sv','rtl/../x.sv','rtl//x.sv','./rtl/x.sv','E:/x.sv','rtl\\x.sv','rtl/x.sv\x00','rtl/']:
            with self.subTest(path=p),self.assertRaises(ValueError):safe_path(p)
    def test_duplicate_keys_rejected_at_all_levels(self):
        v=task_view(record())
        for text in ['{"files":{},"files":{}}','{"files":{"rtl/native_adder.sv":"x","rtl/native_adder.sv":"y"}}']:
            with self.assertRaises(ValueError):candidate_files(text,v)
    def test_missing_extra_unknown_nontext_and_blank_files_rejected(self):
        v=task_view(record())
        for p in [{'files':{}},{'files':{'rtl/native_adder.sv':'x','extra.sv':'y'}},{'files':{'rtl/native_adder.sv':8}},{'files':{'rtl/native_adder.sv':' '}},{'files':{'rtl/native_adder.sv':'x'},'comment':'prose'}]:
            with self.assertRaises(ValueError):candidate_files(json.dumps(p),v)
    def test_multi_file_order_and_all_contents_preserved(self):
        r=record();r['output']['context']={'rtl/top.sv':'','rtl/a.sv':'','rtl/b.sv':''};v=task_view(r);files={'rtl/b.sv':'B\n','rtl/a.sv':'A\n','rtl/top.sv':'T\r\n'};got=candidate_files(json.dumps({'files':files}),v);self.assertEqual(got,files);self.assertEqual(list(got),v['output_paths'])
    def test_no_TopModule_search_rename_or_truncation(self):
        v=task_view(record());code='module native_adder;\n// module TopModule; endmodule\ninitial $display("module TopModule; endmodule");\nendmodule\n';self.assertEqual(candidate_files(json.dumps({'files':{'rtl/native_adder.sv':code}}),v)['rtl/native_adder.sv'],code)
    def test_original_helpers_docs_not_overwritten(self):
        v=task_view(record());files={'rtl/native_adder.sv':'module native_adder; endmodule\n'};a=assembled_files(v,files);self.assertEqual(a['rtl/helper.sv'],v['context']['rtl/helper.sv']);self.assertEqual(a['docs/spec.md'],v['context']['docs/spec.md']);self.assertEqual(a['rtl/native_adder.sv'],files['rtl/native_adder.sv'])
    def test_only_one_json_fence_no_prose(self):
        v=task_view(record());raw=json.dumps({'files':{'rtl/native_adder.sv':'module native_adder; endmodule'}});self.assertEqual(candidate_files('```json\n'+raw+'\n```',v),candidate_files(raw,v))
        for text in ['Explanation\n'+raw,'```verilog\nmodule native_adder; endmodule\n```','```json\n'+raw+'\n```\n```json\n'+raw+'\n```']:
            with self.assertRaises(ValueError):candidate_files(text,v)
    def test_both_arms_share_common_initial_input_and_skills(self):
        v=task_view(record());c=messages(v,G,REPAIR);p=messages(copy.deepcopy(v),G,REPAIR);self.assertEqual(c,p);self.assertEqual(json.loads(c[1]['content']),v);self.assertIn('原题面',c[0]['content'])
    def test_second_round_original_input_previous_all_files_and_actual_diagnostics(self):
        v=task_view(record());files={'rtl/native_adder.sv':'module native_adder; endmodule'};d='Actual compiler diagnostic';out=messages(v,G,REPAIR,files,d);self.assertTrue(out[1]['content'].startswith(user_content(v)+'\nPrevious'));self.assertIn(d,out[1]['content']);self.assertIn(files['rtl/native_adder.sv'],out[1]['content']);self.assertIn('题目要求的模块',out[0]['content'])
    def test_first_round_and_incomplete_repair_rejected(self):
        v=task_view(record())
        with self.assertRaises(ValueError):messages(v,G,REPAIR,diagnostics='invented first diagnostic')
        with self.assertRaises(ValueError):messages(v,G,REPAIR,{},'actual')
    def test_unsupported_skill_change_rejected(self):
        with self.assertRaises(ValueError):messages(task_view(record()),G.replace('TopModule','other'),REPAIR)

if __name__=='__main__':unittest.main()
