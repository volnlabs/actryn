//! Fixed-size fixture-only wire v2. CRC detects corruption, not hostile injection.
pub const VERSION: u16 = 2;
pub const BODY_LEN: usize = 152;
pub const DECODED_LEN: usize = 156;
pub const ENCODED_LEN: usize = 158;

#[repr(u16)]
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum Kind { Hello=1, HelloAck, Rearm, Baseline, Start, Started, Sample,
    SampleApplied, Quiesce, Quiesced, Fault, Observation }
#[repr(u32)]
#[derive(Clone, Copy, Debug, Default, PartialEq, Eq)]
pub enum Status { #[default] Ok=0, Inhibited, Expired, Stale, Limit, Busy,
    Protocol, SinkUnknown, Persistence }
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct Frame {
    pub kind: Kind, pub device:[u8;16], pub boot:u64, pub session:u64,
    pub nonce:[u8;16], pub grant:u64, pub operation:u64, pub stream:u64,
    pub sequence:u64, pub transaction:u64, pub expiry_ns:u64,
    pub controller_ns:u64, pub left:i32, pub right:i32,
    pub encoder_left:i64, pub encoder_right:i64, pub context:u64, pub status:Status,
}
impl Frame {
    pub fn new(kind:Kind)->Self { Self { kind, device:[0;16], boot:0, session:0,
        nonce:[0;16], grant:0, operation:0, stream:0, sequence:0, transaction:0,
        expiry_ns:0, controller_ns:0, left:0, right:0, encoder_left:0,
        encoder_right:0, context:0, status:Status::Ok } }
    pub fn encode(&self)->[u8;ENCODED_LEN] {
        let mut raw=[0u8;DECODED_LEN];
        raw[0..2].copy_from_slice(&VERSION.to_le_bytes());
        raw[2..4].copy_from_slice(&(self.kind as u16).to_le_bytes());
        raw[8..24].copy_from_slice(&self.device);
        raw[40..56].copy_from_slice(&self.nonce);
        macro_rules! put { ($offset:expr,$field:ident) => {
            raw[$offset..$offset+size_of_val(&self.$field)].copy_from_slice(&self.$field.to_le_bytes());
        }; }
        put!(24,boot);put!(32,session);put!(56,grant);put!(64,operation);
        put!(72,stream);put!(80,sequence);put!(88,transaction);put!(96,expiry_ns);
        put!(104,controller_ns);put!(112,left);put!(116,right);
        put!(120,encoder_left);put!(128,encoder_right);put!(136,context);
        raw[144..148].copy_from_slice(&(self.status as u32).to_le_bytes());
        let crc=crc32(&raw[..BODY_LEN]);
        raw[BODY_LEN..].copy_from_slice(&crc.to_le_bytes());
        let mut out=[0;ENCODED_LEN];let mut mark=0;let mut next=1;
        for byte in raw {
            if byte==0 { out[mark]=(next-mark) as u8;mark=next; }
            else { out[next]=byte; }
            next+=1;
        }
        out[mark]=(next-mark) as u8;
        out
    }
    pub fn decode(encoded:&[u8])->Result<Self,DecodeError> {
        let bytes=encoded.strip_suffix(&[0]).unwrap_or(encoded);
        if bytes.len()!=ENCODED_LEN-1 { return Err(DecodeError::Length); }
        let mut raw=[0;DECODED_LEN];let mut i=0;let mut n=0;
        while i<bytes.len() {
            let code=bytes[i] as usize;
            if code==0 || i+code>bytes.len() { return Err(DecodeError::Cobs); }
            i+=1;
            for &byte in &bytes[i..i+code-1] {
                if byte==0 || n>=raw.len() {return Err(DecodeError::Cobs);}
                raw[n]=byte;n+=1;
            }
            i+=code-1;
            if i<bytes.len() && code!=255 {
                if n>=raw.len() {return Err(DecodeError::Length);}
                raw[n]=0;n+=1;
            }
        }
        if n!=DECODED_LEN {return Err(DecodeError::Length);}
        macro_rules! read { ($offset:expr,$ty:ty) => {
            <$ty>::from_le_bytes(raw[$offset..$offset+size_of::<$ty>()].try_into().unwrap())
        }; }
        if crc32(&raw[..BODY_LEN])!=read!(152,u32) {return Err(DecodeError::Crc);}
        if read!(0,u16)!=VERSION {return Err(DecodeError::Version);}
        if read!(4,u32)!=0 || read!(148,u32)!=0 {return Err(DecodeError::Reserved);}
        let kind=match read!(2,u16) {
            1=>Kind::Hello,2=>Kind::HelloAck,3=>Kind::Rearm,4=>Kind::Baseline,
            5=>Kind::Start,6=>Kind::Started,7=>Kind::Sample,8=>Kind::SampleApplied,
            9=>Kind::Quiesce,10=>Kind::Quiesced,11=>Kind::Fault,12=>Kind::Observation,
            _=>return Err(DecodeError::Kind),
        };
        let status=match read!(144,u32) {
            0=>Status::Ok,1=>Status::Inhibited,2=>Status::Expired,3=>Status::Stale,
            4=>Status::Limit,5=>Status::Busy,6=>Status::Protocol,7=>Status::SinkUnknown,
            8=>Status::Persistence,_=>return Err(DecodeError::Status),
        };
        Ok(Self {kind, device:raw[8..24].try_into().unwrap(),boot:read!(24,u64),
            session:read!(32,u64),nonce:raw[40..56].try_into().unwrap(),grant:read!(56,u64),
            operation:read!(64,u64),stream:read!(72,u64),sequence:read!(80,u64),
            transaction:read!(88,u64),expiry_ns:read!(96,u64),controller_ns:read!(104,u64),
            left:read!(112,i32),right:read!(116,i32),encoder_left:read!(120,i64),
            encoder_right:read!(128,i64),context:read!(136,u64),status})
    }
}
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum DecodeError { Length, Cobs, Crc, Version, Reserved, Kind, Status, Overflow }
pub fn crc32(data:&[u8])->u32 {
    let mut crc=!0u32;
    for &byte in data {crc^=byte as u32;for _ in 0..8 {
        crc=(crc>>1)^ (0xedb88320u32.wrapping_mul(crc&1));
    }}
    !crc
}
/// No allocation; oversize input is discarded through the next delimiter.
#[derive(Debug)]
pub struct Parser { bytes:[u8;ENCODED_LEN-1], len:usize, overflow:bool }
impl Default for Parser {fn default()->Self {Self {bytes:[0;ENCODED_LEN-1],len:0,overflow:false}}}
impl Parser {
    pub fn push(&mut self,byte:u8)->Option<Result<Frame,DecodeError>> {
        if byte==0 {
            let result=if self.overflow {Some(Err(DecodeError::Overflow))}
                else if self.len==0 {None} else {Some(Frame::decode(&self.bytes[..self.len]))};
            self.len=0;self.overflow=false;return result;
        }
        if self.len==self.bytes.len() {self.overflow=true;}
        else if !self.overflow {self.bytes[self.len]=byte;self.len+=1;}
        None
    }
}
#[cfg(test)]
mod tests {
    use super::*;
    fn hex(s:&str)->Vec<u8> { s.trim().as_bytes().chunks_exact(2).map(|p|
        u8::from_str_radix(std::str::from_utf8(p).unwrap(),16).unwrap()).collect() }
    #[test]
    fn negative_corpus_and_stream_resynchronization() {
        let good=hex(include_str!("../../../tests/wire/sample.hex"));
        for bad in [include_str!("../../../tests/wire/bad-crc.hex"),
            include_str!("../../../tests/wire/bad-version.hex"),
            include_str!("../../../tests/wire/bad-kind.hex"),
            include_str!("../../../tests/wire/bad-flags.hex"),
            include_str!("../../../tests/wire/bad-reserved.hex"),
            include_str!("../../../tests/wire/bad-status.hex"),
            include_str!("../../../tests/wire/bad-cobs.hex"),
            include_str!("../../../tests/wire/short.hex")] {
            assert!(Frame::decode(&hex(bad)).is_err());
        }
        let mut parser=Parser::default();
        for _ in 0..10000 { assert!(parser.push(1).is_none()); }
        assert_eq!(parser.push(0),Some(Err(DecodeError::Overflow)));
        let mut received=None;
        for byte in good {if let Some(result)=parser.push(byte) {received=Some(result.unwrap());}}
        assert_eq!(received.unwrap().kind,Kind::Sample);
        assert_eq!(crc32(b"123456789"),0xcbf43926);
    }
    #[test]
    fn independent_python_sample() {
        let mut f=Frame::new(Kind::Sample);
        f.device=std::array::from_fn(|i|i as u8);
        f.nonce=std::array::from_fn(|i|i as u8+16);
        f.boot=3;f.session=4;f.grant=5;f.operation=6;f.stream=7;f.sequence=8;
        f.transaction=9;f.expiry_ns=123456789;f.context=1;
        f.left=-100;f.right=200;f.encoder_left=-1234;f.encoder_right=5678;
        assert_eq!(f.encode().as_slice(),hex(include_str!("../../../tests/wire/sample.hex")));
    }
}
