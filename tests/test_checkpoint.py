import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

spec = importlib.util.spec_from_file_location('checkpoint', Path(__file__).resolve().parents[1] / 'Checkpoint-Conversion.py')
checkpoint = importlib.util.module_from_spec(spec)
spec.loader.exec_module(checkpoint)


class CheckpointTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / 'project'
        (self.root / 'app').mkdir(parents=True)
        (self.root / 'voicelines').mkdir()
        self.audio = self.root / 'voicelines/saved.mp3'
        self.audio.write_bytes(b'saved audio fixture')
        self.chunks = [dict(id=0, speaker='NARRATOR', text='Saved.', instruct='', status='done', audio_path='voicelines/saved.mp3'),
                       dict(id=1, speaker='NARRATOR', text='Pending.', instruct='', status='pending', audio_path=None)]
        for name, data in [('chunks.json',self.chunks), ('annotated_script.json',[]), ('voice_config.json',{}), ('recovery-manifest.json',{}), ('app/config.json',{})]:
            (self.root / name).write_text(json.dumps(data),encoding='utf-8')
        (self.root / '.gitignore').write_text('chunks.json\n',encoding='utf-8')

    def test_portable_snapshot_preserves_audio_and_state(self):
        original = checkpoint.digest(self.audio)
        target = self.base / 'checkpoint'
        result = checkpoint.snapshot(self.root,target)
        self.assertEqual((result['completed_segments'],result['pending_segments']),(1,1))
        self.assertEqual(checkpoint.digest(self.audio),original)
        self.assertEqual(checkpoint.digest(target/'voicelines/saved.mp3'),original)
        self.assertEqual((target/'.gitignore').read_text(),'chunks.json\n')
        checkpoint.verify(target)

    def test_modified_checkpoint_audio_is_rejected(self):
        target = self.base / 'checkpoint'
        checkpoint.snapshot(self.root,target)
        (target/'voicelines/saved.mp3').write_bytes(b'changed')
        with self.assertRaisesRegex(ValueError,'mismatch'):
            checkpoint.verify(target)

    def test_missing_done_audio_is_rejected(self):
        self.audio.unlink()
        with self.assertRaisesRegex(ValueError,'missing/empty'):
            checkpoint.audit(self.root)

    def test_active_render_snapshot_is_rejected(self):
        self.chunks[1]['status']='generating'
        (self.root/'chunks.json').write_text(json.dumps(self.chunks),encoding='utf-8')
        with self.assertRaisesRegex(ValueError,'generating'):
            checkpoint.snapshot(self.root,self.base/'unsafe')

    def test_trial_lock_snapshot_is_rejected(self):
        trial=self.root/'forty-batch-trial'
        trial.mkdir()
        (trial/'active.lock').write_text('123')
        with self.assertRaisesRegex(ValueError,'lock'):
            checkpoint.snapshot(self.root,self.base/'unsafe')

    def test_audio_path_cannot_escape_project(self):
        self.chunks[0]['audio_path']='../outside.mp3'
        (self.root/'chunks.json').write_text(json.dumps(self.chunks),encoding='utf-8')
        with self.assertRaises(ValueError):
            checkpoint.audit(self.root)


if __name__=='__main__':
    unittest.main()
