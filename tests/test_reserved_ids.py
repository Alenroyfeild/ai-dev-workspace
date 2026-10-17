from test_ws import Base
from ws import core


class ReservedIdTests(Base):
    def test_windows_device_names_are_refused_as_task_ids(self):
        for task_id in ('CON', 'nul', 'Aux.notes', 'COM1', 'lpt9'):
            with self.subTest(task_id), self.assertRaises(core.WsError) as caught:
                core.task_new(self.root, task_id, 'Reserved name')
            self.assertIn('reserved', str(caught.exception))
        core.task_new(self.root, 'CONSOLE-1', 'Not reserved')  # only exact device names are refused
