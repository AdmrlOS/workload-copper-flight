//! Genuine per-physics-step status, outside the Copper task graph.
use super::*;
use bevy::render::renderer::RenderAdapterInfo;

#[derive(Resource)]
pub(super) struct NativeStatus {
    file: Option<fs::File>,
    last_sim_time: Option<std::time::Duration>,
    seq: u64,
    started: std::time::Instant,
    log_mode: native_contract::NativeLogMode,
    last_depth_check: Option<std::time::Instant>,
    depth_source_seq: Option<u64>,
    depth_preview: Option<String>,
    depth_raster: Option<String>,
}

impl NativeStatus {
    pub(super) fn from_env() -> Self {
        let file = std::env::var_os("COPPER_FLIGHT_TELEMETRY")
            .map(|path| fs::File::create(path).expect("failed to create COPPER_FLIGHT_TELEMETRY"));
        Self {
            file,
            last_sim_time: None,
            seq: 0,
            started: std::time::Instant::now(),
            last_depth_check: None,
            depth_source_seq: None,
            depth_preview: None,
            depth_raster: None,
            log_mode: native_contract::native_log_mode(std::env::var("FLIGHT_NATIVE_LOG_MODE").ok().as_deref())
                .expect("invalid native recording mode"),
        }
    }
}

pub(super) fn export_status(
    mut status: ResMut<NativeStatus>,
    physics_time: Res<Time<Physics>>,
    rc: Res<SimRcInput>,
    vehicles: Query<(&Position, &Rotation, &LinearVelocity), With<Multicopter>>,
    store: Res<sim_zed::SimZedFrameStore>,
    mut copper: ResMut<CopperState>,
    adapter: Option<Res<RenderAdapterInfo>>,
) {
    if status.file.is_none() || status.last_sim_time == Some(physics_time.elapsed()) {
        return;
    }
    status.last_sim_time = Some(physics_time.elapsed());
    let vehicle = vehicles.single().ok();
    let backend = copper.compute.inference_backend();
    let graphics_backend = adapter.as_ref().map(|info| format!("{:?}", info.backend));
    let graphics_device_type = adapter.as_ref().map(|info| format!("{:?}", info.device_type));
    let (policy_observation_seq, policy_prediction_m_s) = store.vitfly_prediction();
    let sample = native_contract::Snapshot {
        seq: status.seq,
        sim_time_s: physics_time.elapsed_secs_f64(),
        position_m: vehicle.map(|(position, _, _)| position.0.to_array()),
        rotation: vehicle.map(|(_, rotation, _)| rotation.0.to_array()),
        velocity_m_s: vehicle.map(|(_, _, velocity)| velocity.0.to_array()),
        armed: rc.armed,
        auto_enabled: rc.auto,
        mode: match rc.mode {
            messages::FlightMode::Acro => "Acro",
            messages::FlightMode::Angle => "Angle",
            messages::FlightMode::PositionHold => "PositionHold",
        },
        world: if cfg!(feature = "forest-world") { "forest" } else { "urban" },
        policy_prediction_m_s,
        policy_observation_seq,
        inference_backend: backend,
        graphics_backend: graphics_backend.as_deref(),
        graphics_adapter: adapter.as_ref().map(|info| info.name.as_str()),
        graphics_vendor_id: adapter.as_ref().map(|info| info.vendor),
        graphics_device_type: graphics_device_type.as_deref(),
    };
    let mut row = sample.json();
    row.pop(); // Extend the unchanged v1 fields with optional genuine Copper diagnostics.
    use std::fmt::Write as _;
    let wall_time_s = status.started.elapsed().as_secs_f64();
    let mut depth_event = None;
    if status.last_depth_check.is_none_or(|last| last.elapsed() >= std::time::Duration::from_millis(500)) {
        status.last_depth_check = Some(std::time::Instant::now());
        match store.observed_depth() {
            Some((seq, handle)) if status.depth_source_seq != Some(seq) => {
                // Both exports observe the same existing completed CPU readback.
                // Never request another GPU readback or retain full data in poses.
                let (preview, raster) = handle.with_inner(|inner| {
                    let mm = inner.as_ref();
                    let width = sim_zed::ZED_SIM_WIDTH as usize;
                    let height = sim_zed::ZED_SIM_HEIGHT as usize;
                    let sim_time_s = physics_time.elapsed_secs_f64();
                    (native_contract::depth_preview_json(mm, width, height, seq, sim_time_s, wall_time_s),
                     native_contract::depth_raster_json(mm, width, height, seq, sim_time_s, wall_time_s))
                });
                status.depth_preview = preview;
                status.depth_raster = raster.map(|(metadata, full)| {
                    depth_event = Some(full);
                    metadata
                });
                status.depth_source_seq = Some(seq);
            }
            None => {
                status.depth_preview = None;
                status.depth_raster = None;
                status.depth_source_seq = None;
            }
            _ => {}
        }
    }
    if let Some(preview) = status.depth_preview.as_ref() {
        write!(row, ",\"depth_preview\":{preview}").expect("format cached observed depth");
    }
    if let Some(metadata) = status.depth_raster.as_ref() {
        write!(row, ",\"depth_raster\":{metadata}").expect("format cached depth raster metadata");
    }
    write!(row, ",\"wall_time_s\":{wall_time_s},\"copper\":{{\"recording_mode\":\"{}\",\"full_recording\":{},\"mcu_iteration_wall_us\":{},\"compute_iteration_wall_us\":{},\"export_wall_s\":{wall_time_s}}}}}",
        status.log_mode.as_str(), status.log_mode == native_contract::NativeLogMode::Full,
        copper.mcu_iteration_wall_us, copper.compute_iteration_wall_us)
        .expect("format native diagnostics");
    let file = status.file.as_mut().expect("status file exists");
    // Publish each full raster once, before its referencing pose, without using
    // a pose sequence number. File is unbuffered; flush() is not durability.
    // We intentionally do not fsync the control loop.
    if let Some(raster) = depth_event {
        writeln!(file, "{{\"schema_version\":1,\"kind\":\"depth-raster\",\"depth_raster\":{raster}}}")
            .expect("failed to write native depth raster");
    }
    writeln!(file, "{row}").expect("failed to write native telemetry");
    status.seq = status.seq.saturating_add(1);
}
