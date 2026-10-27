//! Offline process contract; never called from the Copper task hot path.

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub enum NativeLogMode {
    Full,
    TelemetryOnly,
}

impl NativeLogMode {
    pub fn as_str(self) -> &'static str {
        match self {
            Self::Full => "full",
            Self::TelemetryOnly => "telemetry-only",
        }
    }
}

pub fn native_log_mode(value: Option<&str>) -> Result<NativeLogMode, String> {
    match value.unwrap_or("full") {
        "full" => Ok(NativeLogMode::Full),
        "telemetry-only" => Ok(NativeLogMode::TelemetryOnly),
        _ => Err("FLIGHT_NATIVE_LOG_MODE must be full or telemetry-only".into()),
    }
}

pub fn offscreen_mode(mode: Option<&str>) -> bool {
    matches!(mode, Some("headless") | Some("software"))
}

pub fn episode_seconds(value: Option<&str>) -> Result<f32, String> {
    let value = value.unwrap_or("45");
    let seconds = value
        .parse::<f32>()
        .map_err(|_| "invalid FLIGHT_EPISODE_SECONDS")?;
    if !seconds.is_finite() || seconds <= 0.0 {
        return Err("FLIGHT_EPISODE_SECONDS must be finite and positive".into());
    }
    Ok(seconds)
}

/// Compact CPU observation of the existing millimetre-encoded SimZed buffer.
/// No source timestamp is manufactured: times identify preview sampling only.
pub fn depth_preview_json(
    mm: &[u16], width: usize, height: usize, source_seq: u64,
    sample_sim_time_s: f64, sample_wall_time_s: f64,
) -> Option<String> {
    if width < 32 || height < 24 || width.checked_mul(height) != Some(mm.len())
        || !sample_sim_time_s.is_finite() || !sample_wall_time_s.is_finite() {
        return None;
    }
    let mut data = String::with_capacity(32 * 24 * 2);
    let mut valid = false;
    const HEX: &[u8; 16] = b"0123456789abcdef";
    for y in 0..24 {
        let sy = (2 * y + 1) * height / 48;
        for x in 0..32 {
            let sx = (2 * x + 1) * width / 64;
            let raw = mm[sy * width + sx] as u32;
            let q = if (1..=20000).contains(&raw) {
                valid = true;
                1 + ((raw - 1) * 254 + 9999) / 19999
            } else { 0 };
            data.push(HEX[(q >> 4) as usize] as char);
            data.push(HEX[(q & 15) as usize] as char);
        }
    }
    if !valid { return None; }
    Some(format!(
        "{{\"source\":\"SimZedFrameStore.depth/Copper.ZedSource\",\"source_seq\":{source_seq},\"source_width\":{width},\"source_height\":{height},\"sample_wall_time_s\":{sample_wall_time_s},\"sample_sim_time_s\":{sample_sim_time_s},\"width\":32,\"height\":24,\"encoding\":\"u8-hex\",\"sampling\":\"nearest-cell-center\",\"source_units\":\"millimetres\",\"range_m\":[0.001,20.0],\"invalid_u8\":0,\"invalid_rule\":\"source_mm == 0 or source_mm > 20000\",\"decode_m\":\"(1 + (q - 1) * 19999 / 254) / 1000; q=0 invalid\",\"data\":\"{data}\"}}"
    ))
}

pub struct Snapshot<'a> {
    pub seq: u64,
    pub sim_time_s: f64,
    pub position_m: Option<[f32; 3]>,
    pub rotation: Option<[f32; 4]>,
    pub velocity_m_s: Option<[f32; 3]>,
    pub armed: bool,
    pub auto_enabled: bool,
    pub mode: &'a str,
    pub world: &'a str,
    pub policy_prediction_m_s: Option<[f32; 3]>,
    pub policy_observation_seq: u64,
    pub inference_backend: Option<&'a str>,
    pub graphics_backend: Option<&'a str>,
    pub graphics_adapter: Option<&'a str>,
    pub graphics_vendor_id: Option<u32>,
    pub graphics_device_type: Option<&'a str>,
}

fn json_string(value: Option<&str>) -> String {
    let Some(value) = value else {
        return "null".into();
    };
    let mut output = String::from("\"");
    for character in value.chars() {
        match character {
            '"' => output.push_str("\\\""),
            '\\' => output.push_str("\\\\"),
            c if (c as u32) < 32 => output.push_str(&format!("\\u{:04x}", c as u32)),
            c => output.push(c),
        }
    }
    output.push('"');
    output
}

fn json_vector(value: Option<[f32; 3]>) -> String {
    match value {
        Some([x, y, z]) if x.is_finite() && y.is_finite() && z.is_finite() => {
            format!("{{\"x\":{x},\"y\":{y},\"z\":{z}}}")
        }
        _ => "null".into(),
    }
}

fn json_rotation(value: Option<[f32; 4]>) -> String {
    match value {
        Some([x, y, z, w]) if [x, y, z, w].iter().all(|v| v.is_finite()) => {
            format!("{{\"x\":{x},\"y\":{y},\"z\":{z},\"w\":{w}}}")
        }
        _ => "null".into(),
    }
}

impl Snapshot<'_> {
    pub fn json(&self) -> String {
        format!(
            "{{\"schema_version\":1,\"seq\":{},\"sim_time_s\":{},\"position_m\":{},\"rotation\":{},\"velocity_m_s\":{},\"armed\":{},\"auto_enabled\":{},\"mode\":{},\"world\":{},\"policy_prediction_m_s\":{},\"policy_observation_seq\":{},\"inference_backend\":{},\"inference_count\":null,\"graphics_backend\":{},\"graphics_adapter\":{},\"graphics_vendor_id\":{},\"graphics_device_type\":{}}}",
            self.seq,
            self.sim_time_s,
            json_vector(self.position_m),
            json_rotation(self.rotation),
            json_vector(self.velocity_m_s),
            self.armed,
            self.auto_enabled,
            json_string(Some(self.mode)),
            json_string(Some(self.world)),
            json_vector(self.policy_prediction_m_s),
            self.policy_observation_seq,
            json_string(self.inference_backend),
            json_string(self.graphics_backend),
            json_string(self.graphics_adapter),
            self.graphics_vendor_id.map_or_else(|| "null".into(), |vendor| vendor.to_string()),
            json_string(self.graphics_device_type),
        )
    }
}
