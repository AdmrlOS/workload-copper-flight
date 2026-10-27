//! Offline process contract; never called from the Copper task hot path.

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
