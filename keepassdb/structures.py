"""
It is planned to incorporate this code (or similar) from https://github.com/wummel/python-keepass

This is a very elegant parsing paradigm.

TODO: Merge these with model objects -- or otherwise refactor.
"""
import abc
import struct
import logging
import collections
from datetime import datetime, date
from binascii import hexlify, unhexlify

from keepassdb import exc, const

Marshall = collections.namedtuple('Marshall', ['decode', 'encode'])

marshall_none = Marshall(decode=lambda buf: None,
                         encode=lambda val: None)

marshall_pass = Marshall(decode=lambda buf: buf,
                         encode=lambda val: val)

marshall_ascii = Marshall(decode=lambda buf:hexlify(buf).replace('\0', ''),
                          encode=lambda val:unhexlify(val) + '\0')

marshall_string = Marshall(decode=lambda buf: buf.replace('\0', ''),
                           encode=lambda val: val + '\0')

marshall_short = Marshall(decode=lambda buf: struct.unpack("<H", buf)[0],
                          encode=lambda val: struct.pack("<H", val))

marshall_int = Marshall(decode=lambda buf:struct.unpack("<L", buf)[0],
                        encode=lambda val:struct.pack("<L", val))

class DateMarshall(object):

    def decode(self, buf):
        date_field = struct.unpack('<5B', buf)
        dw1 = date_field[0]
        dw2 = date_field[1]
        dw3 = date_field[2]
        dw4 = date_field[3]
        dw5 = date_field[4]

        y = (dw1 << 6) | (dw2 >> 2)
        mon = ((dw2 & 0x03) << 2) | (dw3 >> 6)
        d = (dw3 >> 1) & 0x1F
        h = ((dw3 & 0x01) << 4) | (dw4 >> 4)
        min_ = ((dw4 & 0x0F) << 2) | (dw5 >> 6)
        s = dw5 & 0x3F
        return datetime(y, mon, d, h, min_, s)
    
    def encode(self, val):
        # Just copied from original KeePassX source
        y, mon, d, h, min_, s = val.timetuple()[:6]

        dw1 = 0x0000FFFF & ((y >> 6) & 0x0000003F)
        dw2 = 0x0000FFFF & ((y & 0x0000003F) << 2 | ((mon >> 2) & 0x00000003))
        dw3 = 0x0000FFFF & (((mon & 0x0000003) << 6) | ((d & 0x0000001F) << 1) \
                | ((h >> 4) & 0x00000001))
        dw4 = 0x0000FFFF & (((h & 0x0000000F) << 4) | ((min_ >> 2) & 0x0000000F))
        dw5 = 0x0000FFFF & (((min_ & 0x00000003) << 6) | (s & 0x0000003F))

        return struct.pack('<5B', dw1, dw2, dw3, dw4, dw5) 
    
marshall_date = DateMarshall()

class StructBase(object):
    'Base class for info type blocks'
    __metaclass__ = abc.ABCMeta
    
    order = None
    
    def __init__(self, buf=None):
        self.order = []         # keep field order
        self.log = logging.getLogger('{0}.{1}'.format(self.__module__, self.__class__.__name__))
        if buf:
            self.decode(buf)

    def __repr__(self):
        ret = [self.__class__.__name__ + ':']
        for num, form in self.format.items():
            attr = form[0]
            if attr is None:
                continue
            try:
                ret.append('  %s=%r' % (attr, getattr(self, attr)))
            except AttributeError:
                pass
        return '\n'.join(ret)

    def __str__(self):
        """
        Return formatted string for this entry.
        """
        dat = self.attributes()
        dat['path'] = self.path()
        return self.label_format % dat

    @abc.abstractproperty
    def label_format(self):
        pass
        
    @abc.abstractproperty
    def format(self):
        pass

    def attributes(self):
        """
        Returns a dict of all this structures attributes and values, skipping
        any attributes that start with an underscore (assumed they should be ignored).
        """
        return dict([(name, getattr(self, name)) for (name, _) in self.format.values() if name is not None and not name.startswith('_')])
    
    def decode(self, buf):
        """
        Set object attributes from buffer.
        
        :raise: keepassdb.exc.ParseError: If errors encountered parsing struct.
        """
        index = 0
        while True:
            #self.log.debug("buffer state: index={0}, buf-ahead={1!r}".format(index, buf[index:]))
            substr = buf[index:index + 6]
            index += 6
            if index > len(buf):
                raise ValueError("Group header offset is out of range: {0}".format(index))
            (typ, siz) = struct.unpack('<H L', substr)
            self.order.append((typ, siz))
            
            substr = buf[index:index + siz]
            index += siz
            encoded = struct.unpack('<%ds' % siz, substr)[0]
            
            (name, marshall) = self.format[typ]
            if name is None:
                break
            try:
                value = marshall.decode(encoded)
                self.log.debug("Decoded field [{0}] to value {1!r}".format(name, value))
            except struct.error, msg:
                msg = '%s, typ=%d[size=%d] -> %s [buf = "%r"]' % \
                    (msg, typ, siz, self.format[typ], encoded)
                raise exc.ParseError(msg)
            setattr(self, name, value)

    def __len__(self):
        length = 0
        for typ, siz in self.order:
            length += 2 + 4 + siz
        return length

    def encode(self):
        """
        Return binary string representation of object.
        
        :rtype: str
        """
        buf = bytearray()
        for typ in sorted(self.format.keys()):
            encoded = None
            if typ != 0xFFFF: # end of block
                (name, marshall) = self.format[typ]
                value = getattr(self, name, None)
                if value is not None:
                    try:
                        encoded = marshall.encode(value)
                        self.log.debug("Encoded field [{0}] to value {1!r}".format(name, encoded))
                    except:
                        self.log.exception("Error encoding key/value: key={0}, value={1!r}".format(name, value))
                        raise
            
            # Note, there is an assumption here that encode() func is returning
            # a byte string (so len = num bytes).  That should be a safe assumption.
            size = len(encoded) if encoded is not None else 0
            packed = struct.pack('<H', typ)
            packed += struct.pack('<I', size)
            if encoded is not None:
                packed += struct.pack('<%ds' % size, encoded)
            buf += packed
            
        return buf

    def path(self):
        path = ""
        parent = self.parent
        while parent:
            path = parent.title + "/" + path
            parent = parent.parent
        return "/" + path

    
class GroupStruct(StructBase):
    '''
    One group: [FIELDTYPE(FT)][FIELDSIZE(FS)][FIELDDATA(FD)]
           [FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)]...
    
    [ 2 bytes] FIELDTYPE
    [ 4 bytes] FIELDSIZE, size of FIELDDATA in bytes
    [ n bytes] FIELDDATA, n = FIELDSIZE
    
    Notes:
    - Strings are stored in UTF-8 encoded form and are null-terminated.
    - FIELDTYPE can be one of the following identifiers:
      * 0000: Invalid or comment block, block is ignored
      * 0001: Group ID, FIELDSIZE must be 4 bytes
              It can be any 32-bit value except 0 and 0xFFFFFFFF
      * 0002: Group name, FIELDDATA is an UTF-8 encoded string
      * 0003: Creation time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 0004: Last modification time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 0005: Last access time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 0006: Expiration time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 0007: Image ID, FIELDSIZE must be 4 bytes
      * 0008: Level, FIELDSIZE = 2
      * 0009: Flags, 32-bit value, FIELDSIZE = 4
      * FFFF: Group entry terminator, FIELDSIZE must be 0
      '''
    
    # Struct attributes
    id = None
    title = None
    icon = None
    level = None
    created = None
    modified = None
    accessed = None
    expires = None
    flags = None
     
    format = {
            0x0: ('_ignored', marshall_none),
            0x1: ('id', marshall_int),
            0x2: ('title', marshall_string),
            0x3: ('created', marshall_date),
            0x4: ('modified', marshall_date),
            0x5: ('accessed', marshall_date),
            0x6: ('expires', marshall_date),
            0x7: ('icon', marshall_int),
            0x8: ('level', marshall_short),
            0x9: ('flags', marshall_int),
            0xFFFF: (None, marshall_none),
        }
    
    @property
    def label_format(self):
        return "Group %(title)s"

class EntryStruct(StructBase):
    '''
    One entry: [FIELDTYPE(FT)][FIELDSIZE(FS)][FIELDDATA(FD)]
           [FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)][FT+FS+(FD)]...

    [ 2 bytes] FIELDTYPE
    [ 4 bytes] FIELDSIZE, size of FIELDDATA in bytes
    [ n bytes] FIELDDATA, n = FIELDSIZE
    
    Notes:
    - Strings are stored in UTF-8 encoded form and are null-terminated.
    - FIELDTYPE can be one of the following identifiers:
      * 0000: Invalid or comment block, block is ignored
      * 0001: UUID, uniquely identifying an entry, FIELDSIZE must be 16
      * 0002: Group ID, identifying the group of the entry, FIELDSIZE = 4
              It can be any 32-bit value except 0 and 0xFFFFFFFF
      * 0003: Image ID, identifying the image/icon of the entry, FIELDSIZE = 4
      * 0004: Title of the entry, FIELDDATA is an UTF-8 encoded string
      * 0005: URL string, FIELDDATA is an UTF-8 encoded string
      * 0006: UserName string, FIELDDATA is an UTF-8 encoded string
      * 0007: Password string, FIELDDATA is an UTF-8 encoded string
      * 0008: Notes string, FIELDDATA is an UTF-8 encoded string
      * 0009: Creation time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 000A: Last modification time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 000B: Last access time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 000C: Expiration time, FIELDSIZE = 5, FIELDDATA = packed date/time
      * 000D: Binary description UTF-8 encoded string
      * 000E: Binary data
      * FFFF: Entry terminator, FIELDSIZE must be 0
    '''
    uuid = None
    group_id = None
    icon = None
    title = None
    url = None
    username = None
    password = None
    notes = None
    created = None
    modified = None
    accessed = None
    expires = None
    binary_desc = None
    binary = None
    
    format = {
            0x0: ('_ignored', marshall_none),
            0x1: ('uuid', marshall_ascii),
            0x2: ('group_id', marshall_int),
            0x3: ('icon', marshall_int),
            0x4: ('title', marshall_string),
            0x5: ('url', marshall_string),
            0x6: ('username', marshall_string),
            0x7: ('password', marshall_string),
            0x8: ('notes', marshall_string),
            0x9: ('created', marshall_date),
            0xa: ('modified', marshall_date),
            0xb: ('accessed', marshall_date),
            0xc: ('expires', marshall_date),
            0xd: ('binary_desc', marshall_string),
            0xe: ('binary', marshall_pass),
            0xFFFF: (None, marshall_none),
            }

    @property
    def label_format(self):
        return "%(title)s: %(username)s %(password)s"


class HeaderStruct(object):
    '''
    The keepass file header.
    
    From the KeePass doc:
    
    Database header: [HeaderStruct]
    
    [ 4 bytes] DWORD    dwSignature1  = 0x9AA2D903
    [ 4 bytes] DWORD    dwSignature2  = 0xB54BFB65
    [ 4 bytes] DWORD    dwFlags
    [ 4 bytes] DWORD    dwVersion       { Ve.Ve.Mj.Mj:Mn.Mn.Bl.Bl }
    [16 bytes] BYTE{16} aMasterSeed
    [16 bytes] BYTE{16} aEncryptionIV
    [ 4 bytes] DWORD    dwGroups        Number of groups in database
    [ 4 bytes] DWORD    dwEntries       Number of entries in database
    [32 bytes] BYTE{32} aContentsHash   SHA-256 hash value of the plain contents
    [32 bytes] BYTE{32} aMasterSeed2    Used for the dwKeyEncRounds AES
                                        master key transformations
    [ 4 bytes] DWORD    dwKeyEncRounds  See above; number of transformations
    
    Notes:
    
    - dwFlags is a bitmap, which can include:
      * PWM_FLAG_SHA2     (1) for SHA-2.
      * PWM_FLAG_RIJNDAEL (2) for AES (Rijndael).
      * PWM_FLAG_ARCFOUR  (4) for ARC4.
      * PWM_FLAG_TWOFISH  (8) for Twofish.
    - aMasterSeed is a salt that gets hashed with the transformed user master key
      to form the final database data encryption/decryption key.
      * FinalKey = SHA-256(aMasterSeed, TransformedUserMasterKey)
    - aEncryptionIV is the initialization vector used by AES/Twofish for
      encrypting/decrypting the database data.
    - aContentsHash: "plain contents" refers to the database file, minus the
      database header, decrypted by FinalKey.
      * PlainContents = Decrypt_with_FinalKey(DatabaseFile - DatabaseHeader)
    '''
    signature1 = None
    signature2 = None
    flags = None
    version = None
    seed_rand = None
    encryption_iv = None
    ngroups = None
    nentries = None
    contents_hash = None
    seed_key = None
    key_enc_rounds = None
    
    # format = '<L L L L 16s 16s L L 32s 32s L'
    
    format = (
        ('signature1', 4, 'L'),
        ('signature2', 4, 'L'),
        ('flags', 4, 'L'),
        ('version', 4, 'L'),
        ('seed_rand', 16, '16s'),
        ('encryption_iv', 16, '16s'),
        ('ngroups', 4, 'L'),
        ('nentries', 4, 'L'),
        ('contents_hash', 32, '32s'),
        ('seed_key', 32, '32s'),
        ('key_enc_rounds', 4, 'L'),
    )

    length = 124

    SHA2 = 1
    RIJNDAEL = 2
    AES = 2
    ARC_FOUR = 4
    TWO_FISH = 8
    
    encryption_flags = (
        ('SHA2', SHA2),
        ('Rijndael', RIJNDAEL),
        ('AES', AES),
        ('ArcFour', ARC_FOUR),
        ('TwoFish', TWO_FISH),
    )

    def __init__(self, buf=None):
        'Create a header, read self from binary string if given'
        if buf:
            self.decode(buf)

    def __repr__(self):
        ret = ['Header:']
        for field in self.format:
            # field is a tuple (name, size, type)
            name = field[0]
            ret.append('\t%s %r' % (name, getattr(self, name)))
        return '\n'.join(ret)
    
    def __len__(self):
        """ This will equal 124 for the V1 database. """
        length = 0
        for typ, siz, _ in self.format:
            length += siz
        return length
    
    def encryption_type(self):
        for encflag in self.encryption_flags[1:]:
            if encflag[1] & self.flags:
                return encflag[0]
        return 'Unknown'

    def encode(self):
        'Provide binary string representation'
        ret = ""
        for name, bytes, typecode in self.format:
            value = getattr(self, name)
            buf = struct.pack('<' + typecode, value)
            ret += buf
        return ret

    def decode(self, buf):
        'Fill self from binary string.'
        index = 0
        for (name, nbytes, typecode) in self.format:
            string = buf[index:index + nbytes]
            index += nbytes
            value = struct.unpack('<' + typecode, string)[0]
            setattr(self, name, value)
        if const.DB_SIGNATURE1 != self.signature1 or \
                const.DB_SIGNATURE2 != self.signature2:
            msg = 'Bad signatures: {0} {0}'.format(hex(self.signature1),
                                                   hex(self.signature2))
            raise exc.InvalidDatabase(msg)


