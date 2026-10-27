//! Coarse Bevy-side status: file I/O and reflection stay outside Copper processing.
use super::*;
use bevy::render::renderer::RenderAdapterInfo;
use std::time::{Duration, Instant};

#[derive(Resource)]
pub(super) struct NativeStatus {
    file: Option<fs::File>,
    last: Option<Instant>,
    seq: u64,
}

impl NativeStatus {
    pub(super) fn from_env() -> Self {
        let file = std::env::var_os("COPPER_FLIGHT_TELEMETRY")
            .map(|path| fs::File::create(path).expect("failed to create COPPER_FLIGHT_TELEMETRY"));
        Self {
            file,
            last: None,
            seq: 0,
        }
    }
}

pub(super) fn export_status(
    mut status: ResMut<NativeStatus>,
    physics_time: Res<Time<Physics>>,
    rc: Res<SimRcInput>,
    vehicles: Query<(&GlobalTransform, &LinearVelocity), With<Multicopter>>,
    store: Res<sim_zed::SimZedFrameStore>,
    mut copper: ResMut<CopperState>,
    adapter: Option<Res<RenderAdapterInfo>>,
) {
    if status.file.is_none()
        || status
            .last
            .is_some_and(|last| last.elapsed() < Duration::from_millis(100))
    {
        return;
    }
    status.last = Some(Instant::now());
    let vehicle = vehicles.single().ok();
    let backend = copper.compute.inference_backend();
    let graphics_backend = adapter.as_ref().map(|info| format!("{:?}", info.backend));
    let graphics_device_type = adapter.as_ref().map(|info| format!("{:?}", info.device_type));
    let (policy_observation_seq, policy_prediction_m_s) = store.vitfly_prediction();
    let sample = native_contract::Snapshot {
        seq: status.seq,
        sim_time_s: physics_time.elapsed_secs_f64(),
        position_m: vehicle.map(|(transform, _)| transform.translation().to_array()),
        rotation: vehicle.map(|(transform, _)| transform.rotation().to_array()),
        velocity_m_s: vehicle.map(|(_, velocity)| velocity.0.to_array()),
        armed: rc.armed,
        auto_enabled: rc.auto,
        mode: match rc.mode {
            messages::FlightMode::Acro => "Acro",
            messages::FlightMode::Angle => "Angle",
            messages::FlightMode::PositionHold => "PositionHold",
        },
        world: if cfg!(feature = "forest-world") {
            "forest"
        } else {
            "urban"
        },
        policy_prediction_m_s,
        policy_observation_seq,
        inference_backend: backend,
        graphics_backend: graphics_backend.as_deref(),
        graphics_adapter: adapter.as_ref().map(|info| info.name.as_str()),
        graphics_vendor_id: adapter.as_ref().map(|info| info.vendor),
        graphics_device_type: graphics_device_type.as_deref(),
    };
    let row = sample.json();
    let file = status.file.as_mut().expect("status file exists");
    writeln!(file, "{row}")
        .and_then(|_| file.flush())
        .expect("failed to write native telemetry");
    status.seq = status.seq.saturating_add(1);
}
