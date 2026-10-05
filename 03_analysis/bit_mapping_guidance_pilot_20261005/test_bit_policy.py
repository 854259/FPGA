"""Pure FAKE skill/message fixtures; never model, EDA or quality evidence."""
import hashlib
from pathlib import Path
import tempfile
import types
import unittest
from unittest.mock import patch

import bit_policy


APPENDIX_BYTES = (
    '在确定拼接、移位、选路公式和位常量时，按题面核对数值对应：输出第 i 位来自哪个输入第 j 位。'
    '把选择值的首末合法值代入索引，检查范围和方向；把位掩码还原为实际置 1 的位号逐项核对。'
    '左右等位置称呼只按题面定义解释，不能代替 i+1、i-1 的关系。保持原输出格式，不输出核对过程。\n'
).encode('utf-8')
APPENDIX_SHA256 = '518a93fef56513e39467b67be1031c23fd1bf37ed9bcc1a672aa050e82dc6bce'
GENERATION = '  FAKE generation\r\n原 generation 尾空格  \n\n'
REPAIR = '  FAKE repair\r\n原 repair 尾空格  \n'
SUPPORT_SENTINEL = 'FAKE_PRIVATE_SUPPORT_METADATA_MUST_NEVER_REACH_SYSTEM'


def fixture(root):
    (root / 'APPENDIX.txt').write_bytes(APPENDIX_BYTES)
    (root / 'BIT_MAPPING_SUPPORT.json').write_text(SUPPORT_SENTINEL, encoding='utf-8')


def fake_runtime():
    def original():
        return GENERATION, REPAIR
    return types.SimpleNamespace(skill_texts=original), original


class BitPolicy(unittest.TestCase):
    def test_appendix_exact_utf8_bytes_hash_and_trailing_lf(self):
        self.assertEqual(len(APPENDIX_BYTES), 390)
        self.assertEqual(hashlib.sha256(APPENDIX_BYTES).hexdigest(), APPENDIX_SHA256)
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            actual = bit_policy.appendix(root=root)
            self.assertEqual(actual.encode('utf-8'), APPENDIX_BYTES)
            self.assertTrue(actual.endswith('\n'))
            self.assertFalse(actual.startswith('\ufeff'))

    def test_install_returns_original_function_and_keeps_repair_unchanged(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            for arm in ['C', 'P']:
                runtime, original = fake_runtime()
                returned = bit_policy.install(runtime, arm, root=root)
                generation, repair = runtime.skill_texts()
                with self.subTest(arm=arm):
                    self.assertIs(returned, original)
                    self.assertEqual(original(), (GENERATION, REPAIR))
                    self.assertEqual(repair.encode('utf-8'), REPAIR.encode('utf-8'))
                    expected = GENERATION.encode('utf-8') + (APPENDIX_BYTES if arm == 'P' else b'')
                    self.assertEqual(generation.encode('utf-8'), expected)

    def test_initial_and_repair_system_order_no_strip_or_extra_divider(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            for arm in ['C', 'P']:
                runtime, _ = fake_runtime()
                bit_policy.install(runtime, arm, root=root)
                wrapped_generation, wrapped_repair = runtime.skill_texts()
                for attempt in [0, 1]:
                    expected = GENERATION.encode('utf-8')
                    if arm == 'P':
                        expected += APPENDIX_BYTES
                    if attempt:
                        expected += b'\n' + REPAIR.encode('utf-8')
                    actual = bit_policy.system_message(GENERATION, REPAIR, arm, attempt, root=root)
                    runtime_message = wrapped_generation + ('\n' + wrapped_repair if attempt else '')
                    with self.subTest(arm=arm, attempt=attempt):
                        self.assertEqual(actual.encode('utf-8'), expected)
                        self.assertEqual(runtime_message.encode('utf-8'), expected)
                        if arm == 'P' and attempt:
                            self.assertLess(actual.index(APPENDIX_BYTES.decode('utf-8')), actual.index(REPAIR))

    def test_candidate_install_does_not_leak_into_separate_control_runtime(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            candidate, original = fake_runtime()
            control = types.SimpleNamespace(skill_texts=original)
            bit_policy.install(candidate, 'P', root=root)
            bit_policy.install(control, 'C', root=root)
            self.assertEqual(control.skill_texts(), (GENERATION, REPAIR))
            self.assertEqual(candidate.skill_texts(), (GENERATION + APPENDIX_BYTES.decode('utf-8'), REPAIR))

    def test_changed_content_bom_newline_or_truncation_is_rejected_by_sha(self):
        alterations = [b'X' + APPENDIX_BYTES[1:], b'\xef\xbb\xbf' + APPENDIX_BYTES,
                       APPENDIX_BYTES + b'\n', APPENDIX_BYTES[:-1],
                       APPENDIX_BYTES.replace(b'\n', b'\r\n')]
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            for altered in alterations:
                (root / 'APPENDIX.txt').write_bytes(altered)
                with self.subTest(bytes=len(altered)):
                    with self.assertRaises((AssertionError, ValueError, RuntimeError)):
                        bit_policy.appendix(root=root)
                    runtime, _ = fake_runtime()
                    with self.assertRaises((AssertionError, ValueError, RuntimeError)):
                        bit_policy.install(runtime, 'P', root=root)
                        runtime.skill_texts()
                    with self.assertRaises((AssertionError, ValueError, RuntimeError)):
                        bit_policy.system_message(GENERATION, REPAIR, 'P', 0, root=root)

    def test_only_appendix_is_read_and_support_metadata_never_enters_system(self):
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            fixture(root)
            allowed = (root / 'APPENDIX.txt').resolve()
            original_open, opened = Path.open, []

            def appendix_only_open(path, *args, **kwargs):
                self.assertEqual(path.resolve(), allowed, 'Policy must read only frozen APPENDIX.txt')
                opened.append(path.resolve())
                return original_open(path, *args, **kwargs)

            messages = []
            with patch.object(Path, 'open', new=appendix_only_open):
                self.assertEqual(bit_policy.appendix(root=root).encode('utf-8'), APPENDIX_BYTES)
                for arm in ['C', 'P']:
                    runtime, _ = fake_runtime()
                    bit_policy.install(runtime, arm, root=root)
                    generation, repair = runtime.skill_texts()
                    for attempt in [0, 1]:
                        messages.append(generation + ('\n' + repair if attempt else ''))
                        messages.append(bit_policy.system_message(GENERATION, REPAIR, arm, attempt, root=root))
            self.assertTrue(opened)
            self.assertEqual(set(opened), {allowed})
            self.assertTrue(all(SUPPORT_SENTINEL not in message for message in messages))


if __name__ == '__main__':
    unittest.main()
