import os
import unittest
from unittest import mock
import test_team_folder
from ws import core, folder_io


class FolderWriteTests(unittest.TestCase):
    setUp = test_team_folder.TeamFolderTests.setUp
    record = test_team_folder.TeamFolderTests.record

    def test_raw_backup_read_compare_and_replace_preserve_foreign_edits(self):
        name = 'entries/' + self.entry + '.md';path = self.folder/name
        path.write_bytes(b'original\r\n');info=self.folder.stat();identity=[info.st_dev,info.st_ino]
        self.assertEqual(folder_io.read(self.folder,identity,name),'original\r\n')
        folder_io.replace(self.folder,identity,name,'published\n','original\r\n')
        with self.assertRaises(core.WsError):folder_io.replace(self.folder,identity,name,'wrong\n','original\r\n')
        self.assertEqual(path.read_bytes(),b'published\n')
        folder_io.replace(self.folder,identity,name,None,'published\n');self.assertFalse(path.exists())

    @unittest.skipIf(os.name=='nt','POSIX descriptor/symlink replacement race.')
    def test_root_and_entry_directory_swaps_never_write_replacement(self):
        for component in ('root','entries'):
            with self.subTest(component=component):
                host=self.base/component;host.mkdir();entries=host/'entries';entries.mkdir()
                (entries/'record.md').write_text('original');info=host.stat();identity=[info.st_dev,info.st_ino]
                foreign=self.base/('foreign-'+component);foreign.mkdir()
                parked=self.base/('parked-'+component);selected=host if component=='root' else entries
                native=os.replace;swapped=[]
                def race(source,target,*args,**kwargs):
                    if target=='record.md' and kwargs.get('dst_dir_fd') is not None:
                        selected.rename(parked);selected.symlink_to(foreign,target_is_directory=True);swapped.append(True)
                    return native(source,target,*args,**kwargs)
                with mock.patch.object(os,'replace',side_effect=race):
                    folder_io.replace(host,identity,'entries/record.md','published','original')
                self.assertTrue(swapped);self.assertFalse(list(foreign.iterdir()))
                actual=parked/'entries/record.md' if component=='root' else parked/'record.md'
                self.assertEqual(actual.read_text(),'published')
