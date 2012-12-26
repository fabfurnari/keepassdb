"""
Unit tests for the main Database class.
"""
import os.path
from StringIO import StringIO

from freezegun import freeze_time

from keepassdb import Database, model, exc

from tests import TestBase, RESOURCES_DIR

class DatabaseTest(TestBase):
        
    def test_init_missing_fil(self):
        """ Test initialization w/ invalid file. """
        with self.assertRaises(IOError):
            db = Database('./missing-path.kdb')
    
    @freeze_time("2012-12-25 08:00:00")    
    def test_init_new(self):
        """ Test initializing new database. """
        db = Database()
        db.create_default_group()
        exp_g = model.Group(title=u'Internet', icon=1, level=0, id=1, db=db, parent=db.root)
        
        self.assertEquals(1, len(db.groups))
        self.assertEquals(exp_g.__dict__, db.groups[0].__dict__)
        self.assertEquals([], db.groups[0].entries)
       
    def test_load_file(self):
        """
        Test loading from file path.
        """
        db = Database()
        kdb = os.path.join(RESOURCES_DIR, 'example.kdb')
        with self.assertRaisesRegexp(ValueError, r'Password and/or keyfile is required.'):
            db.load(kdb)
        
        db.load(kdb, password='test')
        self.assertEquals(kdb, db.filepath)
        
    def test_load_stream(self):
        """
        Test loading from stream.
        """
        db = Database()
        kdb = os.path.join(RESOURCES_DIR, 'example.kdb')
        with open(kdb, 'rb') as fp:
            stream = StringIO(fp.read())
            stream.seek(0)
            with self.assertRaisesRegexp(ValueError, r'Password and/or keyfile is required.'):
                db.load(stream)
            stream.seek(0)
            db.load(stream, password='test')
    
    def test_load(self):
        """ Test loading database """
        db = Database()
        kdb = os.path.join(RESOURCES_DIR, 'example.kdb')
        db.load(kdb, password='test')
        
        print db.groups
        
        # Make assertions about the structure.
        top_groups = [g.title for g in db.root.children]
        self.assertEquals(['Internet', 'eMail', 'Backup'], top_groups)
        self.assertEquals(['A1', 'B1', 'C1'], [g.title for g in db.root.children[0].children])
        self.assertEquals(set(['AEntry1', 'AEntry2', 'AEntry3']), set([e.title for e in db.root.children[0].children[0].entries]))
        self.assertEquals(['A2'], [g.title for g in db.root.children[0].children[0].children])
        
        # Good enough for now ;)
    
    @freeze_time("2012-12-25 08:00:00")        
    def test_save(self):
        """ Test creating and saving a database. """
        
        db = Database()
        i_group = db.create_default_group()
        e_group = db.create_group(title=u'eMail')
        
        e1 = i_group.create_entry(title=u'FirstEntry', username=u'root', password=u'test', url=u'http://example.com')
        e2 = i_group.create_entry(title=u'SecondEntry', username=u'root', password=u'test', url=u'http://example.com')
        e3 = e_group.create_entry(title=u'ThirdEntry', username=u'root', password=u'test', url=u'http://example.com')
        
        ser = db.to_dict(hierarchy=True, hide_passwords=True)
        
        with self.assertRaisesRegexp(ValueError, r"Unable to save without target file."):
            db.save(password='test')
        
        stream = StringIO()
        db.save(dbfile=stream, password='test')
        
        stream.seek(0)
        
        with self.assertRaises(exc.AuthenticationError):
            db.load(dbfile=stream, password='wrong')
        
        stream.seek(0)
        db.load(dbfile=stream, password='test')
        
        self.maxDiff = None
        
        self.assertEquals(ser, db.to_dict(hierarchy=True, hide_passwords=True))
        
        
class LockingDabaseTest(TestBase):
    pass