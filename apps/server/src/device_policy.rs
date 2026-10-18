// SPDX-License-Identifier: Apache-2.0
//! Loader for the fixed cgroup-device program data; no runtime policy input.

use anyhow::{ensure, Context, Result};
use serde::{Deserialize, Serialize};
use sha2::{Digest, Sha256};
use std::{
    fs::{File, OpenOptions},
    os::{
        fd::{AsRawFd, FromRawFd, OwnedFd},
        unix::fs::{MetadataExt, OpenOptionsExt},
    },
    path::Path,
};

#[cfg(not(all(target_endian = "little", target_pointer_width = "64")))]
compile_error!("fixed device policy supports only the qualified 64-bit little-endian targets");

const INSTRUCTIONS: &[[u8; 8]] = &include!("../bpf/device_policy.insns");
const LICENSE: &[u8] = b"Apache-2.0\0";
const CGROUP_DEVICE: u32 = 6;
const PROGRAM_TYPE: u32 = 15;
const ALLOW_MULTI: u32 = 2;
const MAX_PROGRAMS: usize = 64;

// Zero-initialized prefixes of Linux6.12 union bpf_attr. No optional fields used.
#[repr(C)]
struct Load {
    prog_type: u32,
    insn_cnt: u32,
    insns: u64,
    license: u64,
    log_level: u32,
    log_size: u32,
    log_buf: u64,
    kern_version: u32,
    prog_flags: u32,
    prog_name: [u8; 16],
    prog_ifindex: u32,
    expected_attach_type: u32,
}
#[repr(C)]
struct Attach {
    target_fd: u32,
    attach_bpf_fd: u32,
    attach_type: u32,
    attach_flags: u32,
    replace_bpf_fd: u32,
}
#[repr(C)]
struct InfoRequest {
    bpf_fd: u32,
    info_len: u32,
    info: u64,
}
#[repr(C)]
#[derive(Default)]
struct ProgramInfo {
    prog_type: u32,
    id: u32,
    tag: [u8; 8],
}
#[repr(C)]
struct Query {
    target_fd: u32,
    attach_type: u32,
    query_flags: u32,
    attach_flags: u32,
    prog_ids: u64,
    prog_cnt: u32,
    pad: u32,
}

#[derive(Clone, Debug, PartialEq, Eq, Serialize, Deserialize)]
#[serde(deny_unknown_fields)]
pub struct Proof {
    pub program_id: u32,
    pub instruction_sha256: String,
}

#[derive(Clone, Debug, PartialEq, Eq)]
pub struct Programs {
    pub ids: Vec<u32>,
    pub attach_flags: u32,
}

pub(crate) fn instruction_sha256() -> String {
    let mut digest = Sha256::new();
    for instruction in INSTRUCTIONS {
        digest.update(instruction);
    }
    format!("{:x}", digest.finalize())
}

fn directory(cgroup: &Path) -> Result<File> {
    let fd = OpenOptions::new()
        .read(true)
        .custom_flags(libc::O_DIRECTORY | libc::O_NOFOLLOW | libc::O_CLOEXEC)
        .open(cgroup)
        .context("open device policy cgroup directory")?;
    ensure!(
        fd.metadata()?.is_dir(),
        "device policy target is not a directory"
    );
    Ok(fd)
}

fn query_fd(fd: &File, effective: bool) -> Result<Programs> {
    let mut ids = [0_u32; MAX_PROGRAMS];
    let mut query = Query {
        target_fd: fd.as_raw_fd() as u32,
        attach_type: CGROUP_DEVICE,
        query_flags: u32::from(effective),
        attach_flags: 0,
        prog_ids: ids.as_mut_ptr() as u64,
        prog_cnt: MAX_PROGRAMS as u32,
        pad: 0,
    };
    // SAFETY: query and its initialized fixed-size ID buffer remain live for the syscall.
    let result = unsafe { libc::syscall(libc::SYS_bpf, 16, &mut query, size_of::<Query>()) };
    if result < 0 {
        return Err(std::io::Error::last_os_error()).context("query device policy programs");
    }
    ensure!(
        query.prog_cnt as usize <= MAX_PROGRAMS,
        "device program inventory overflow"
    );
    ensure!(
        !effective || query.attach_flags == 0,
        "unexpected effective-query flags"
    );
    let mut ids = ids[..query.prog_cnt as usize].to_vec();
    ids.sort_unstable();
    ensure!(
        ids.iter().all(|id| *id > 0) && ids.windows(2).all(|v| v[0] != v[1]),
        "invalid device program IDs"
    );
    Ok(Programs {
        ids,
        attach_flags: query.attach_flags,
    })
}

/// Query a bounded, sorted direct or effective inventory; never retry on overflow.
pub fn programs(cgroup: &Path, effective: bool) -> Result<Programs> {
    query_fd(&directory(cgroup)?, effective)
}

/// Attach once after runtime create and before application start. On success the
/// cgroup owns a reference; closing our program FD never detaches the filter.
/// Caller owns task/cgroup teardown after any failure or later proof mismatch.
pub fn install(cgroup: &Path, expected_inode: u64) -> Result<Proof> {
    let cgroup = directory(cgroup)?;
    ensure!(
        expected_inode != 0 && cgroup.metadata()?.ino() == expected_inode,
        "device policy cgroup identity changed"
    );
    let existing = query_fd(&cgroup, false)?;
    ensure!(
        !existing.ids.is_empty()
            && existing.ids.len() < MAX_PROGRAMS
            && existing.attach_flags == ALLOW_MULTI,
        "runtime device policy missing, full, or not ALLOW_MULTI"
    );
    let mut log = [0_u8; 16 * 1024];
    let mut request = Load {
        prog_type: PROGRAM_TYPE,
        insn_cnt: INSTRUCTIONS.len() as u32,
        insns: INSTRUCTIONS.as_ptr() as u64,
        license: LICENSE.as_ptr() as u64,
        log_level: 1,
        log_size: log.len() as u32,
        log_buf: log.as_mut_ptr() as u64,
        kern_version: 0,
        prog_flags: 0,
        prog_name: *b"actryn_devices\0\0",
        prog_ifindex: 0,
        expected_attach_type: CGROUP_DEVICE,
    };
    // SAFETY: all referenced buffers are valid, fixed-size, and live for this call.
    let raw = unsafe { libc::syscall(libc::SYS_bpf, 5, &mut request, size_of::<Load>()) };
    if raw < 0 {
        let error = std::io::Error::last_os_error();
        let end = log.iter().position(|b| *b == 0).unwrap_or(log.len());
        return Err(error).with_context(|| {
            format!(
                "load fixed device policy: {}",
                String::from_utf8_lossy(&log[..end])
            )
        });
    }
    // SAFETY: successful BPF_PROG_LOAD returns a newly owned file descriptor.
    let program = unsafe { OwnedFd::from_raw_fd(raw as i32) };
    let mut info = ProgramInfo::default();
    let mut request = InfoRequest {
        bpf_fd: program.as_raw_fd() as u32,
        info_len: size_of::<ProgramInfo>() as u32,
        info: (&mut info as *mut ProgramInfo) as u64,
    };
    // SAFETY: request refers to the live, initialized info prefix and owned program.
    let result =
        unsafe { libc::syscall(libc::SYS_bpf, 15, &mut request, size_of::<InfoRequest>()) };
    if result < 0 {
        return Err(std::io::Error::last_os_error()).context("identify loaded device policy");
    }
    ensure!(
        info.prog_type == PROGRAM_TYPE
            && info.id > 0
            && request.info_len >= size_of::<ProgramInfo>() as u32,
        "invalid loaded device policy identity"
    );
    let mut request = Attach {
        target_fd: cgroup.as_raw_fd() as u32,
        attach_bpf_fd: program.as_raw_fd() as u32,
        attach_type: CGROUP_DEVICE,
        attach_flags: ALLOW_MULTI,
        replace_bpf_fd: 0,
    };
    // SAFETY: both owned descriptors remain live. No replace, override or detach.
    let result = unsafe { libc::syscall(libc::SYS_bpf, 8, &mut request, size_of::<Attach>()) };
    if result < 0 {
        return Err(std::io::Error::last_os_error()).context("attach fixed device policy");
    }
    let proof = Proof {
        program_id: info.id,
        instruction_sha256: instruction_sha256(),
    };
    let direct = query_fd(&cgroup, false)?;
    let effective = query_fd(&cgroup, true)?;
    ensure!(
        direct.attach_flags == ALLOW_MULTI
            && direct.ids.len() == existing.ids.len() + 1
            && existing.ids.iter().all(|id| direct.ids.contains(id)),
        "device policy attachment inventory changed"
    );
    verify(&proof, &direct.ids, &effective.ids)?;
    Ok(proof)
}

/// This validates the fixed policy identity and membership, not caller-provided
/// IDs' provenance. Callers obtain both lists from programs() and pin snapshots.
pub fn verify(proof: &Proof, direct_ids: &[u32], effective_ids: &[u32]) -> Result<()> {
    ensure!(
        proof.program_id > 0 && proof.instruction_sha256 == instruction_sha256(),
        "wrong fixed device policy proof"
    );
    for ids in [direct_ids, effective_ids] {
        ensure!(
            !ids.is_empty() && ids.len() <= MAX_PROGRAMS && ids.iter().all(|id| *id > 0),
            "invalid device program inventory"
        );
        ensure!(
            ids.iter()
                .enumerate()
                .all(|(index, id)| !ids[..index].contains(id)),
            "duplicate device program ID"
        );
        ensure!(
            ids.contains(&proof.program_id),
            "fixed device policy missing"
        );
    }
    ensure!(
        direct_ids.iter().all(|id| effective_ids.contains(id)),
        "direct device program not effective"
    );
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    // Execute the actual included program data, rather than a second policy function.
    // Only the fixed program's mapless, helper-free instruction subset is supported.
    fn execute(program: &[[u8; 8]], access: u16, kind: u16, major: u32, minor: u32) -> u64 {
        let context = [u32::from(kind) | (u32::from(access) << 16), major, minor];
        let mut registers = [0_u64; 11];
        let mut pc = 0_usize;
        for _ in 0..64 {
            let instruction = program
                .get(pc)
                .expect("instruction pointer outside program");
            let destination = usize::from(instruction[1] & 15);
            let source = usize::from(instruction[1] >> 4);
            assert!(destination < registers.len() && source < registers.len());
            let offset = i16::from_le_bytes([instruction[2], instruction[3]]);
            let immediate = i32::from_le_bytes(instruction[4..8].try_into().unwrap());
            let mut branch = false;
            match instruction[0] {
                0x61 => {
                    assert_eq!(source, 1, "only context loads are supported");
                    assert!([0, 4, 8].contains(&offset));
                    registers[destination] = u64::from(context[offset as usize / 4]);
                }
                0xbc => registers[destination] = u64::from(registers[source] as u32),
                0xb4 => registers[destination] = u64::from(immediate as u32),
                0x54 => {
                    registers[destination] =
                        u64::from(registers[destination] as u32 & immediate as u32)
                }
                0x74 => {
                    assert!((0..32).contains(&immediate));
                    registers[destination] =
                        u64::from((registers[destination] as u32) >> immediate);
                }
                0x15 => branch = registers[destination] == immediate as i64 as u64,
                0x55 => branch = registers[destination] != immediate as i64 as u64,
                0x95 => return registers[0],
                code => panic!("unsupported BPF instruction {code:#x}"),
            }
            let next = pc as i64 + 1 + if branch { i64::from(offset) } else { 0 };
            assert!(
                next >= 0 && next < program.len() as i64,
                "invalid BPF branch"
            );
            pc = next as usize;
        }
        panic!("instruction bound exceeded")
    }

    #[test]
    fn actual_program_device_matrix() {
        for kind in [0, 1, 2, 3, u16::MAX] {
            for major in [0, 1, 5, 10, 136, u32::MAX] {
                for minor in [0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10, 200, u32::MAX] {
                    for access in [0, 1, 2, 3, 4, 5, 6, 7, 8, 0x8000, u16::MAX] {
                        let expected = kind == 2
                            && major == 1
                            && [3, 5, 8, 9].contains(&minor)
                            && [2, 4, 6].contains(&access);
                        assert_eq!(
                            execute(INSTRUCTIONS, access, kind, major, minor),
                            u64::from(expected),
                            "access={access:#x} type={kind} device={major}:{minor}"
                        );
                    }
                }
            }
        }
    }

    #[test]
    fn actual_program_all_access_bits_and_device_types() {
        for value in 0..=u16::MAX {
            assert_eq!(
                execute(INSTRUCTIONS, value, 2, 1, 3),
                u64::from([2, 4, 6].contains(&value)),
                "access={value:#x}"
            );
            assert_eq!(
                execute(INSTRUCTIONS, 2, value, 1, 3),
                u64::from(value == 2),
                "device type={value:#x}"
            );
        }
    }

    #[test]
    fn proof_requires_fixed_program_in_direct_and_effective_sets() {
        let good = Proof {
            program_id: 42,
            instruction_sha256: instruction_sha256(),
        };
        verify(&good, &[7, 42], &[7, 42, 99]).unwrap();
        for (direct, effective) in [
            (&[7][..], &[7, 42][..]),
            (&[42][..], &[7][..]),
            (&[][..], &[42][..]),
            (&[42][..], &[][..]),
        ] {
            assert!(verify(&good, direct, effective).is_err());
        }
        assert!(verify(
            &Proof {
                program_id: 0,
                ..good.clone()
            },
            &[0],
            &[0]
        )
        .is_err());
        assert!(verify(
            &Proof {
                instruction_sha256: "0".repeat(64),
                ..good
            },
            &[42],
            &[42]
        )
        .is_err());
    }

    #[test]
    fn proof_rejects_duplicate_invalid_and_unbounded_inventories() {
        let proof = Proof {
            program_id: 42,
            instruction_sha256: instruction_sha256(),
        };
        for bad in [vec![42, 42], vec![0, 42], (1..=65).collect()] {
            assert!(verify(&proof, &bad, &[42]).is_err());
            assert!(verify(&proof, &[42], &bad).is_err());
        }
        assert!(verify(&proof, &[7, 42], &[42]).is_err());
    }

    #[test]
    fn fixed_program_has_no_helpers_maps_or_hidden_instructions() {
        assert_eq!(LICENSE, b"Apache-2.0\0");
        assert_eq!(INSTRUCTIONS.len(), 20);
        for instruction in INSTRUCTIONS {
            assert!([0x61, 0xbc, 0xb4, 0x54, 0x74, 0x15, 0x55, 0x95].contains(&instruction[0]));
            // This excludes CALL/helper/kfunc(0x85), map/pseudo LD_IMM64(0x18),
            // every store, and any instruction outside the reviewed interpreter.
            if instruction[0] == 0x61 {
                assert_eq!(instruction[1] >> 4, 1);
                assert!([0, 4, 8].contains(&i16::from_le_bytes([instruction[2], instruction[3]])));
            }
        }
    }

    #[test]
    fn linux_612_syscall_prefix_layouts() {
        assert_eq!(size_of::<Load>(), 72);
        assert_eq!(std::mem::offset_of!(Load, insns), 8);
        assert_eq!(std::mem::offset_of!(Load, log_buf), 32);
        assert_eq!(std::mem::offset_of!(Load, expected_attach_type), 68);
        assert_eq!(size_of::<Attach>(), 20);
        assert_eq!(size_of::<InfoRequest>(), 16);
        assert_eq!(size_of::<ProgramInfo>(), 16);
        assert_eq!(size_of::<Query>(), 32);
        assert_eq!(std::mem::offset_of!(Query, prog_ids), 16);
        assert_eq!(std::mem::offset_of!(Query, prog_cnt), 24);
    }

    #[test]
    fn rejects_wrong_inode_nondirectory_and_symlink_before_bpf() {
        let directory = tempfile::tempdir().unwrap();
        let inode = directory.path().metadata().unwrap().ino();
        assert!(install(directory.path(), inode.wrapping_add(1))
            .unwrap_err()
            .to_string()
            .contains("identity changed"));
        assert!(install(directory.path(), 0).is_err());
        let file = directory.path().join("file");
        std::fs::write(&file, []).unwrap();
        assert!(install(&file, file.metadata().unwrap().ino()).is_err());
        let link = directory.path().join("link");
        std::os::unix::fs::symlink(directory.path(), &link).unwrap();
        assert!(install(&link, inode).is_err());
        assert!(programs(&link, true).is_err());
    }
}
