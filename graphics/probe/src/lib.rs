pub const WIDTH: usize = 64;
pub const HEIGHT: usize = 64;
pub const ROW_BYTES: usize = 256;

pub fn validate_depth(bytes: &[u8]) -> Result<(f32, f32), String> {
    if bytes.len() != ROW_BYTES * HEIGHT { return Err("unexpected Depth32Float readback length".into()); }
    let sample = |x: usize, y: usize| {
        let offset = y * ROW_BYTES + x * 4;
        f32::from_le_bytes(bytes[offset..offset+4].try_into().unwrap())
    };
    let center = sample(32, 32);
    let background = sample(4, 4);
    if !center.is_finite() || !background.is_finite()
        || (center - 0.25).abs() > 0.0001 || (background - 1.0).abs() > 0.0001 {
        return Err(format!("depth assertions failed: center={center}, background={background}"));
    }
    Ok((center, background))
}

pub fn validate_adapter(vendor: u32, cpu: bool, vulkan: bool, software: bool) -> Result<(), String> {
    if vulkan && (if software { cpu } else { vendor == 0x10de && !cpu }) { Ok(()) }
    else { Err(format!("adapter rejected: vendor={vendor:#x}, cpu={cpu}, vulkan={vulkan}, software={software}")) }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn raster_fixture() -> Vec<u8> {
        let mut bytes = vec![0; ROW_BYTES * HEIGHT];
        for word in bytes.chunks_exact_mut(4) { word.copy_from_slice(&1f32.to_le_bytes()); }
        let center = 32 * ROW_BYTES + 32 * 4;
        bytes[center..center+4].copy_from_slice(&0.25f32.to_le_bytes());
        bytes
    }
    #[test]
    fn adapter_gate_is_nvidia_non_cpu_unless_explicit_software() {
        assert!(super::validate_adapter(0x10de, false, true, false).is_ok());
        assert!(super::validate_adapter(0x10005, true, true, false).is_err());
        assert!(super::validate_adapter(0x10de, true, true, false).is_err());
        assert!(super::validate_adapter(0x10de, false, false, false).is_err());
        assert!(super::validate_adapter(0x10005, true, true, true).is_ok());
        assert!(super::validate_adapter(0x10de, false, true, true).is_err());
    }

    #[test]
    fn validates_known_center_and_background() {
        assert_eq!(validate_depth(&raster_fixture()).unwrap(), (0.25, 1.0));
    }
    #[test]
    fn rejects_empty_constant_nonfinite_and_wrong_samples() {
        assert!(validate_depth(&[]).is_err());
        for value in [0f32, 1f32, f32::NAN, f32::INFINITY] {
            let bytes = value.to_le_bytes().repeat(WIDTH * HEIGHT);
            assert!(validate_depth(&bytes).is_err());
        }
        let mut bytes = raster_fixture();
        bytes[4 * ROW_BYTES + 4 * 4..4 * ROW_BYTES + 4 * 4 + 4].copy_from_slice(&0.25f32.to_le_bytes());
        assert!(validate_depth(&bytes).is_err());
    }
}
