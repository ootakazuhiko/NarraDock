"""Typed script extraction uses only neutral in-memory data; no media is generated."""
import copy
import hashlib
import json
from pathlib import Path
import unittest
from unittest.mock import patch

import narradock_script as scripts


def canonical(document):
    return json.dumps(document, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")


class ScriptTests(unittest.TestCase):
    def setUp(self):
        self.project = "sample-project"
        self.document = {"schema_version": "script-blocks-0.1", "project_id": self.project,
            "content_id": "sample-script", "language": "ja",
            "blocks": [{"id": "opening", "kind": "body", "text": " BGMという語も本文です。\r\n次の行。\t "},
                       {"id": "screen-note", "kind": "directive", "text": "画面を切り替える。"},
                       {"id": "closing", "kind": "body", "text": "終わり。🎵"}]}

    def fingerprint(self, document=None, **kwargs):
        return scripts.script_fingerprint(self.document if document is None else document,
            project_id=kwargs.get("project_id", self.project))

    def extract(self, document=None, **kwargs):
        document = self.document if document is None else document
        return scripts.extract_script(document, project_id=kwargs.get("project_id", self.project),
            expected_fingerprint=kwargs.get("expected_fingerprint", self.fingerprint(document, **kwargs)))

    def rejected(self, function, *args, **kwargs):
        with self.assertRaises(scripts.ScriptError) as caught:
            function(*args, **kwargs)
        self.assertEqual("Script could not be validated", str(caught.exception))
        self.assertIsNone(caught.exception.__cause__)

    def reject_document(self, document):
        for function in (scripts.snapshot_script, scripts.script_fingerprint):
            self.rejected(function, document, project_id=self.project)
        self.rejected(scripts.extract_script, document, project_id=self.project, expected_fingerprint="a" * 64)

    def test_neutral_example_loads_and_extracts_in_order(self):
        data = (Path(__file__).resolve().parents[1] / "examples/script-contract.json").read_bytes()
        document = scripts.load_script(data, project_id=self.project)
        result = self.extract(document)
        self.assertEqual(["opening", "closing"], [block["id"] for block in result["body_blocks"]])
        self.assertEqual((2, 1), (result["body_block_count"], result["directive_block_count"]))
        self.assertEqual([{**{key: document["blocks"][1][key] for key in ("id", "text")}, "source_index": 1}],
                         result["directives"])
        self.assertEqual("script-extraction-0.1", result["schema_version"])
        self.assertEqual("body-directive-0.1", result["extractor_version"])
        self.assertEqual("preserve-0.1", result["text_policy"])

    def test_explicit_kind_selects_body_without_guessing_from_words(self):
        self.document["blocks"][0]["text"] = "画面を切り替える。BGM、停止、音量という語を説明します。"
        self.document["blocks"][1]["text"] = "A sentence that could also be ordinary prose."
        result = self.extract()
        self.assertEqual(self.document["blocks"][0]["text"], result["body_blocks"][0]["text"])
        self.assertNotIn(self.document["blocks"][1]["text"], [b["text"] for b in result["body_blocks"]])
        self.assertEqual(self.document["blocks"][1]["text"], result["directives"][0]["text"])

    def test_per_block_hashes_cover_exact_utf8_text_and_not_json(self):
        result = self.extract()
        for original, block in zip((self.document["blocks"][0], self.document["blocks"][2]), result["body_blocks"]):
            encoded = original["text"].encode("utf-8")
            self.assertEqual(original["text"], block["text"])
            self.assertEqual(len(encoded), block["size_bytes"])
            self.assertEqual(hashlib.sha256(encoded).hexdigest(), block["sha256"])
            self.assertNotEqual(hashlib.sha256(json.dumps(original["text"]).encode()).hexdigest(), block["sha256"])
        self.assertGreater(result["body_blocks"][1]["size_bytes"], len(result["body_blocks"][1]["text"]))

    def test_canonical_revisions_ignore_json_layout_key_order_and_escapes(self):
        pretty = json.dumps(self.document, ensure_ascii=False, indent=4).encode()
        reversed_keys = dict(reversed(list(self.document.items())))
        reversed_keys["blocks"] = [dict(reversed(list(block.items()))) for block in self.document["blocks"]]
        escaped = json.dumps(reversed_keys, ensure_ascii=True).encode()
        self.assertNotEqual(hashlib.sha256(pretty).hexdigest(), hashlib.sha256(escaped).hexdigest())
        for data in (pretty, escaped, b" \n" + canonical(self.document) + b"\t "):
            loaded = scripts.load_script(data, project_id=self.project)
            self.assertEqual(self.document, loaded)
            self.assertEqual(self.fingerprint(), self.fingerprint(loaded))
            self.assertEqual(self.extract(), self.extract(loaded))

    def test_revisions_have_distinct_canonical_domains(self):
        result = self.extract()
        projection = {"schema_version": "script-body-0.1", "project_id": self.project,
            "content_id": "sample-script", "language": "ja", "text_policy": "preserve-0.1",
            "blocks": [{"id": block["id"], "text": block["text"]}
                       for block in self.document["blocks"] if block["kind"] == "body"]}
        self.assertEqual(hashlib.sha256(canonical(self.document)).hexdigest(), result["script_fingerprint"])
        self.assertEqual(hashlib.sha256(canonical(projection)).hexdigest(), result["body_fingerprint"])
        self.assertNotEqual(result["script_fingerprint"], result["body_fingerprint"])

    def test_fixed_revision_vectors_include_unicode_and_preserved_crlf(self):
        document = {"schema_version": "script-blocks-0.1", "project_id": "p", "content_id": "c",
            "language": "en", "blocks": [{"id": "b", "kind": "body", "text": " A\r\né "},
                                         {"id": "d", "kind": "directive", "text": "Note."}]}
        result = self.extract(document, project_id="p")
        self.assertEqual("4b6ddbe3db75432e723bd28689434cd1b208ead7e125db84849f683603d12dac", result["script_fingerprint"])
        self.assertEqual("8eb5cfa57343ace0eee2e3ecbe0fae60c26efe17c5dc221b02e22b2f5ba7bada", result["body_fingerprint"])

    def test_directive_changes_preserve_body_identity_but_change_script_identity(self):
        original = self.extract()
        for change in ("edit", "insert", "move", "delete", "rename"):
            document = copy.deepcopy(self.document)
            if change == "edit": document["blocks"][1]["text"] = "Different direction."
            if change == "insert": document["blocks"].insert(0, {"id": "new-direction", "kind": "directive", "text": "Another direction."})
            if change == "move": document["blocks"].append(document["blocks"].pop(1))
            if change == "delete": del document["blocks"][1]
            if change == "rename": document["blocks"][1]["id"] = "renamed-direction"
            with self.subTest(change=change):
                result = self.extract(document)
                self.assertNotEqual(original["script_fingerprint"], result["script_fingerprint"])
                self.assertEqual(original["body_fingerprint"], result["body_fingerprint"])
                self.assertEqual(original["body_blocks"], result["body_blocks"])
                for direction in result["directives"]:
                    source = document["blocks"][direction["source_index"]]
                    self.assertEqual((source["id"], source["text"]), (direction["id"], direction["text"]))

    def test_body_text_identity_order_count_and_kind_changes_change_both_revisions(self):
        original = self.extract()
        for change in ("text", "id", "order", "delete", "insert", "kind"):
            document = copy.deepcopy(self.document)
            if change == "text": document["blocks"][0]["text"] += "追記。"
            if change == "id": document["blocks"][0]["id"] = "renamed-body"
            if change == "order": document["blocks"][0], document["blocks"][2] = document["blocks"][2], document["blocks"][0]
            if change == "delete": del document["blocks"][0]
            if change == "insert": document["blocks"].insert(0, {"id": "new-body", "kind": "body", "text": "Inserted."})
            if change == "kind": document["blocks"][1]["kind"] = "body"
            with self.subTest(change=change):
                result = self.extract(document)
                for field in ("script_fingerprint", "body_fingerprint"):
                    self.assertNotEqual(original[field], result[field])

    def test_scope_and_language_bind_both_revisions_even_when_text_is_identical(self):
        original = self.extract()
        for key, value in (("project_id", "another-project"), ("content_id", "another-content"), ("language", "en")):
            document = copy.deepcopy(self.document)
            document[key] = value
            result = self.extract(document, project_id=document["project_id"])
            self.assertEqual(original["body_blocks"], result["body_blocks"])
            for field in ("script_fingerprint", "body_fingerprint"):
                self.assertNotEqual(original[field], result[field])
        self.rejected(scripts.snapshot_script, self.document, project_id="another-project")

    def test_stale_full_selection_is_rejected_even_for_a_directive_only_change(self):
        selected = self.fingerprint()
        self.document["blocks"][1]["text"] += " Updated."
        self.rejected(scripts.extract_script, self.document, project_id=self.project, expected_fingerprint=selected)
        self.assertEqual(self.fingerprint(), self.extract()["script_fingerprint"])

    def test_invalid_selected_fingerprints_are_rejected(self):
        for selected in (None, True, 123, [], "", "a" * 63, "A" * 64, "a" * 64, self.fingerprint() + "\n"):
            with self.subTest(type=type(selected).__name__):
                self.rejected(scripts.extract_script, self.document, project_id=self.project, expected_fingerprint=selected)

    def test_text_is_not_joined_and_block_segmentation_is_significant(self):
        first, second = copy.deepcopy(self.document), copy.deepcopy(self.document)
        for document, parts in ((first, ("ab", "c")), (second, ("a", "bc"))):
            document["blocks"][0]["text"], document["blocks"][2]["text"] = parts
        self.assertNotEqual(self.extract(first)["body_fingerprint"], self.extract(second)["body_fingerprint"])
        self.assertEqual(["ab", "c"], [b["text"] for b in self.extract(first)["body_blocks"]])

    def test_spaces_line_endings_and_unicode_normalization_are_not_changed(self):
        variants = ("line\nnext", "line\r\nnext", "line\rnext", " line\nnext", "line\nnext ",
                    "line\tnext", "é", "e\u0301", "Ａ", "A", "👩\u200d🔬", "text\u2028next\u2029", "text\ufeff", "\ufefftext")
        revisions = []
        for text in variants:
            document = copy.deepcopy(self.document)
            document["blocks"][0]["text"] = text
            result = self.extract(document)
            self.assertEqual(text, result["body_blocks"][0]["text"])
            revisions.append(result["body_fingerprint"])
        self.assertEqual(len(variants), len(set(revisions)))

    def test_block_count_and_body_presence_are_required(self):
        for blocks in ([], (), {}, None, [self.document["blocks"][1]]):
            document = {**self.document, "blocks": blocks}
            self.reject_document(document)

    def test_all_root_and_block_fields_are_exact(self):
        for root in (True, [], None, 1, "script"):
            self.reject_document(root)
        for location in ("root", "block"):
            template = self.document if location == "root" else self.document["blocks"][0]
            for missing in list(template) + [None]:
                document = copy.deepcopy(self.document)
                target = document if location == "root" else document["blocks"][0]
                if missing is None: target["extra"] = "Unexpected."
                else: del target[missing]
                self.reject_document(document)
        for field, value in (("schema_version", "script-blocks-0.2"), ("schema_version", True),
                             ("language", ""), ("language", "EN"), ("language", "en_XX"),
                             ("language", "a" * 21), ("language", 1)):
            self.reject_document({**self.document, field: value})
        for kind in ("speech", "Body", True, [], None):
            document = copy.deepcopy(self.document)
            document["blocks"][0]["kind"] = kind
            self.reject_document(document)

    def test_identifiers_and_duplicate_ids_are_rejected_across_all_kinds(self):
        for identifier in ("", "A", "a_b", "a--b", "a-", "1a", "日本語", "a" * 65, True, 1, []):
            for location in ("project_id", "content_id", "block"):
                document = copy.deepcopy(self.document)
                if location == "block": document["blocks"][0]["id"] = identifier
                else: document[location] = identifier
                self.reject_document(document)
        duplicate = copy.deepcopy(self.document)
        duplicate["blocks"][1]["id"] = duplicate["blocks"][0]["id"]
        self.reject_document(duplicate)
        self.document["blocks"][0]["id"] = "a" * 64
        self.assertEqual("a" * 64, self.extract()["body_blocks"][0]["id"])

    def test_invalid_block_text_is_rejected_for_both_kinds(self):
        invalid = [None, 1, True, [], "", " \t\r\n\u3000\ufeff", "\ud800", "x\udfff"]
        invalid += ["x" + chr(code) for code in list(range(32)) + list(range(127, 160)) if code not in (9, 10, 13)]
        for kind in ("body", "directive"):
            for value in invalid:
                document = copy.deepcopy(self.document)
                document["blocks"][0].update(kind=kind, text=value)
                self.reject_document(document)

    def test_text_limit_counts_unicode_code_points_and_includes_equality(self):
        for kind in ("body", "directive"):
            for unit in ("x", "🎵"):
                document = copy.deepcopy(self.document)
                document["blocks"][0].update(kind=kind, text=unit * scripts.MAX_TEXT)
                self.assertEqual(document, scripts.snapshot_script(document, project_id=self.project))
                self.extract(document)
                document["blocks"][0]["text"] += unit
                self.reject_document(document)

    def test_block_limit_includes_equality_and_never_truncates(self):
        document = {**self.document, "blocks": [{"id": f"block-{i}", "kind": "body" if i == 0 else "directive",
                                                "text": "Neutral text."} for i in range(scripts.MAX_BLOCKS)]}
        result = self.extract(document)
        self.assertEqual(1, result["body_block_count"])
        self.assertEqual(scripts.MAX_BLOCKS - 1, result["directive_block_count"])
        self.assertEqual(scripts.MAX_BLOCKS - 1, result["directives"][-1]["source_index"])
        document["blocks"].append({"id": "one-extra", "kind": "body", "text": "Excess."})
        self.reject_document(document)

    def test_json_loader_rejects_bad_encoding_duplicates_constants_and_structure(self):
        data = canonical(self.document)
        bad = [b"", b"\xff", b"\xef\xbb\xbf" + data, data + b"x", b"null", b"true", b"[]", b"{}",
               b"[" * 1100 + b"]" * 1100, b'1' * 5000,
               data.replace(b'"kind":"body"', b'"kind":"body","kind":"body"', 1),
               data.replace(b'"project_id":"sample-project"', b'"project_id":"sample-project","project_id":"sample-project"'),
               data.replace(b'"language":"ja"', b'"language":NaN'),
               data.replace(b'"language":"ja"', b'"language":Infinity'),
               data.replace(b'"language":"ja"', b'"language":-Infinity')]
        for value in bad:
            self.rejected(scripts.load_script, value, project_id=self.project)

    def test_json_input_limit_is_checked_before_decode_and_accepts_exact_size(self):
        data = canonical(self.document)
        padded = data + b" " * (scripts.MAX_BYTES - len(data))
        self.assertEqual(self.document, scripts.load_script(padded, project_id=self.project))
        with patch.object(scripts.json, "loads") as parse:
            self.rejected(scripts.load_script, padded + b" ", project_id=self.project)
            parse.assert_not_called()
        for value in (data.decode(), bytearray(data), memoryview(data), None):
            self.rejected(scripts.load_script, value, project_id=self.project)

    def test_in_memory_canonical_byte_limit_includes_equality(self):
        document = {**self.document, "blocks": [{"id": f"block-{i}", "kind": "body", "text": "x" * 3000}
                                                for i in range(300)]}
        remaining = scripts.MAX_BYTES - len(canonical(document))
        self.assertGreater(remaining, 0)
        for block in document["blocks"]:
            amount = min(remaining, 1000)
            block["text"] += "x" * amount
            remaining -= amount
        self.assertEqual(0, remaining)
        self.assertEqual(scripts.MAX_BYTES, len(canonical(document)))
        self.assertEqual(document, scripts.snapshot_script(document, project_id=self.project))
        self.assertEqual(300, self.extract(document)["body_block_count"])
        document["blocks"][-1]["text"] += "x"
        self.reject_document(document)

    def test_total_utf8_text_budget_is_checked_for_in_memory_inputs(self):
        document = {**self.document, "blocks": [{"id": f"block-{i}", "kind": "body", "text": "🎵" * 4000}
                                                for i in range(70)]}
        self.reject_document(document)

    def test_result_encoding_limit_is_checked_before_return(self):
        expected = self.extract()
        size = len(canonical(expected))
        with patch.object(scripts, "MAX_RESULT_BYTES", size):
            self.assertEqual(expected, self.extract())
        with patch.object(scripts, "MAX_RESULT_BYTES", size - 1):
            self.rejected(scripts.extract_script, self.document, project_id=self.project,
                          expected_fingerprint=self.fingerprint())

    def test_snapshot_and_extracted_records_are_independent(self):
        baseline = copy.deepcopy(self.document)
        snapshot = scripts.snapshot_script(self.document, project_id=self.project)
        result = self.extract(snapshot)
        self.document["blocks"][0]["text"] = "Changed caller data."
        self.document["blocks"].reverse()
        self.assertEqual(baseline, snapshot)
        snapshot["blocks"][1]["text"] = "Changed snapshot."
        self.assertEqual(baseline["blocks"][1]["text"], result["directives"][0]["text"])
        result["body_blocks"][0]["text"] = "Changed output."
        self.assertEqual(baseline["blocks"][0]["text"], snapshot["blocks"][0]["text"])

    def test_extraction_uses_frozen_fields_after_canonical_snapshot(self):
        expected = self.extract()
        selected = self.fingerprint()
        original = scripts._canonical_bytes
        def mutate(document, limit):
            output = original(document, limit)
            self.document["blocks"][0]["text"] = "Mutated caller body."
            self.document["blocks"][1]["kind"] = "body"
            self.document["language"] = "en"
            return output
        with patch.object(scripts, "_canonical_bytes", side_effect=mutate):
            result = scripts.extract_script(self.document, project_id=self.project, expected_fingerprint=selected)
        self.assertEqual(expected, result)

    def test_custom_primitive_subclasses_cannot_run_copy_or_access_hooks(self):
        class CustomDict(dict):
            def __getitem__(self, key): raise AssertionError("Access hook called")
        class CustomList(list):
            def __iter__(self): raise AssertionError("Iteration hook called")
        class CustomString(str):
            def __eq__(self, other): raise AssertionError("Comparison hook called")
            __hash__ = str.__hash__
        class CustomBytes(bytes):
            def decode(self, *args, **kwargs): raise AssertionError("Decode hook called")
        self.reject_document(CustomDict(self.document))
        self.reject_document({**self.document, "blocks": CustomList(self.document["blocks"])})
        for field in ("schema_version", "project_id", "content_id", "language"):
            self.reject_document({**self.document, field: CustomString(self.document[field])})
        for field in ("id", "kind", "text"):
            document = copy.deepcopy(self.document)
            document["blocks"][0][field] = CustomString(document["blocks"][0][field])
            self.reject_document(document)
        document = {CustomString(key): value for key, value in self.document.items()}
        self.reject_document(document)
        self.rejected(scripts.snapshot_script, self.document, project_id=CustomString(self.project))
        self.rejected(scripts.extract_script, self.document, project_id=self.project,
                      expected_fingerprint=CustomString(self.fingerprint()))
        self.rejected(scripts.load_script, CustomBytes(canonical(self.document)), project_id=self.project)

    def test_directives_are_data_and_operations_perform_no_file_or_command_io(self):
        self.document["blocks"][1]["text"] = 'Open <example> and show "BGM"; do not interpret this text.'
        data, selected = canonical(self.document), self.fingerprint()
        with patch("builtins.open", side_effect=AssertionError("Unexpected file access")), \
                patch("subprocess.run", side_effect=AssertionError("Unexpected command")):
            loaded = scripts.load_script(data, project_id=self.project)
            result = scripts.extract_script(loaded, project_id=self.project, expected_fingerprint=selected)
        self.assertEqual(self.document["blocks"][1]["text"], result["directives"][0]["text"])


if __name__ == "__main__":
    unittest.main()
