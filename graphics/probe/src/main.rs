use copper_vulkan_depth_probe::{validate_adapter, validate_depth, HEIGHT, ROW_BYTES, WIDTH};
use serde_json::{json, Value};
use std::{future::Future, sync::{mpsc, Arc}, task::{Context, Poll, Wake, Waker}, time::{Duration, Instant}};

const NVIDIA_ICD: &str = "/etc/vulkan/icd.d/nvidia_icd.json";
const SOFTWARE_ICD: &str = "/usr/share/vulkan/icd.d/lvp_icd.json";
const DEADLINE: Duration = Duration::from_secs(25);

struct ThreadWake(std::thread::Thread);
impl Wake for ThreadWake { fn wake(self: Arc<Self>) { self.0.unpark(); } }
fn block_on<F: Future>(future: F) -> F::Output {
    let waker = Waker::from(Arc::new(ThreadWake(std::thread::current())));
    let mut cx = Context::from_waker(&waker);
    let mut future = std::pin::pin!(future);
    loop {
        match future.as_mut().poll(&mut cx) {
            Poll::Ready(value) => return value,
            Poll::Pending => std::thread::park_timeout(Duration::from_millis(10)),
        }
    }
}

fn rasterize(software: bool, report: &mut Value) -> Result<(), String> {
    let mut descriptor = wgpu::InstanceDescriptor::new_without_display_handle();
    descriptor.backends = wgpu::Backends::VULKAN;
    let instance = wgpu::Instance::new(descriptor);
    let adapter = block_on(instance.request_adapter(&wgpu::RequestAdapterOptions {
        power_preference: wgpu::PowerPreference::HighPerformance,
        compatible_surface: None,
        force_fallback_adapter: false,
    })).map_err(|e| format!("surface-free adapter request: {e}"))?;
    let info = adapter.get_info();
    report["adapter"] = json!({"name":info.name, "vendor":format!("0x{:04x}",info.vendor),
        "device":info.device, "device_type":format!("{:?}",info.device_type),
        "backend":format!("{:?}",info.backend), "driver":info.driver, "driver_info":info.driver_info});
    validate_adapter(info.vendor, info.device_type == wgpu::DeviceType::Cpu,
                     info.backend == wgpu::Backend::Vulkan, software)?;
    let (device, queue) = block_on(adapter.request_device(&wgpu::DeviceDescriptor {
        label: Some("bounded-surface-free-depth-probe"), ..Default::default()
    })).map_err(|e| format!("request device: {e}"))?;
    let extent = wgpu::Extent3d { width: WIDTH as u32, height: HEIGHT as u32, depth_or_array_layers: 1 };
    let depth = device.create_texture(&wgpu::TextureDescriptor {
        label: Some("actual-raster-depth"), size: extent, mip_level_count: 1, sample_count: 1,
        dimension: wgpu::TextureDimension::D2, format: wgpu::TextureFormat::Depth32Float,
        usage: wgpu::TextureUsages::RENDER_ATTACHMENT | wgpu::TextureUsages::COPY_SRC,
        view_formats: &[],
    });
    let view = depth.create_view(&wgpu::TextureViewDescriptor::default());
    let shader = device.create_shader_module(wgpu::ShaderModuleDescriptor {
        label: Some("known-triangle-at-depth-quarter"), source: wgpu::ShaderSource::Wgsl(include_str!("triangle.wgsl").into()),
    });
    let pipeline = device.create_render_pipeline(&wgpu::RenderPipelineDescriptor {
        label: Some("triangle-depth-rasterizer"), layout: None,
        vertex: wgpu::VertexState { module: &shader, entry_point: Some("vs_main"),
            compilation_options: Default::default(), buffers: &[] },
        primitive: wgpu::PrimitiveState::default(),
        depth_stencil: Some(wgpu::DepthStencilState {
            format: wgpu::TextureFormat::Depth32Float, depth_write_enabled: Some(true),
            depth_compare: Some(wgpu::CompareFunction::Always), stencil: Default::default(), bias: Default::default(),
        }),
        multisample: Default::default(), fragment: None, multiview_mask: None, cache: None,
    });
    let readback = device.create_buffer(&wgpu::BufferDescriptor {
        label: Some("depth-to-CPU"), size: (ROW_BYTES * HEIGHT) as u64,
        usage: wgpu::BufferUsages::COPY_DST | wgpu::BufferUsages::MAP_READ, mapped_at_creation: false,
    });
    let mut encoder = device.create_command_encoder(&wgpu::CommandEncoderDescriptor { label: Some("raster-and-copy") });
    {
        let mut pass = encoder.begin_render_pass(&wgpu::RenderPassDescriptor {
            label: Some("real-triangle-not-enumeration"), color_attachments: &[],
            depth_stencil_attachment: Some(wgpu::RenderPassDepthStencilAttachment {
                view: &view, depth_ops: Some(wgpu::Operations { load: wgpu::LoadOp::Clear(1.0), store: wgpu::StoreOp::Store }),
                stencil_ops: None,
            }), ..Default::default()
        });
        pass.set_pipeline(&pipeline);
        pass.draw(0..3, 0..1);
    }
    encoder.copy_texture_to_buffer(
        wgpu::TexelCopyTextureInfo { texture: &depth, mip_level: 0, origin: wgpu::Origin3d::ZERO,
            aspect: wgpu::TextureAspect::DepthOnly },
        wgpu::TexelCopyBufferInfo { buffer: &readback, layout: wgpu::TexelCopyBufferLayout {
            offset: 0, bytes_per_row: Some(ROW_BYTES as u32), rows_per_image: Some(HEIGHT as u32) } }, extent);
    let submission = queue.submit(Some(encoder.finish()));
    let (tx, rx) = mpsc::channel();
    readback.slice(..).map_async(wgpu::MapMode::Read, move |result| { let _ = tx.send(result); });
    device.poll(wgpu::PollType::Wait { submission_index: Some(submission), timeout: Some(Duration::from_secs(10)) })
        .map_err(|e| format!("bounded submission poll: {e}"))?;
    rx.recv_timeout(Duration::from_secs(1)).map_err(|e| format!("map callback deadline: {e}"))?
        .map_err(|e| format!("map failed: {e}"))?;
    let mapped = readback.slice(..).get_mapped_range();
    let (center, background) = validate_depth(&mapped)?;
    report["depth"] = json!({"center":center,"background":background,"center_xy":[32,32],
        "background_xy":[4,4],"tolerance":0.0001,"mapped_bytes":mapped.len()});
    drop(mapped);
    readback.unmap();
    report["rasterized"] = json!(true);
    report["status"] = json!("passed");
    Ok(())
}

fn main() {
    let arguments: Vec<String> = std::env::args().skip(1).collect();
    let software = arguments == ["--software-verification"];
    let icd = if software { SOFTWARE_ICD } else { NVIDIA_ICD };
    // Set before creating threads or loading Vulkan. Explicit software mode must
    // override BOTH variables even when the containing image forces NVIDIA.
    std::env::set_var("VK_DRIVER_FILES", icd);
    std::env::set_var("VK_ICD_FILENAMES", icd);
    let mut report = json!({"schema":1,"status":"failed","rasterized":false,
        "proof":if software {"software-not-Jetson-proof"} else {"NVIDIA-hardware-required"},
        "vk_driver_files":icd,"vk_icd_filenames":icd,"compatible_surface":null,
        "force_fallback_adapter":false,"width":WIDTH,"height":HEIGHT,"format":"Depth32Float",
        "bytes_per_row":ROW_BYTES,"clear_depth":1.0,"triangle_depth":0.25,"deadline_seconds":DEADLINE.as_secs()});
    if !arguments.is_empty() && !software {
        report["error"] = json!("only optional --software-verification is accepted");
        println!("{report}"); std::process::exit(2);
    }
    let (done_tx, done_rx) = mpsc::channel::<()>();
    let mut timeout_report = report.clone();
    std::thread::spawn(move || {
        if matches!(done_rx.recv_timeout(DEADLINE), Err(mpsc::RecvTimeoutError::Timeout)) {
            timeout_report["error"] = json!("whole-process graphics probe deadline exceeded");
            println!("{timeout_report}"); std::process::exit(124);
        }
    });
    let started = Instant::now();
    let result = std::panic::catch_unwind(std::panic::AssertUnwindSafe(|| rasterize(software, &mut report)));
    let exit = match result {
        Ok(Ok(())) => 0,
        Ok(Err(error)) => { report["error"] = json!(error); 1 },
        Err(_) => { report["error"] = json!("wgpu/Vulkan panic; inspect stderr"); 1 },
    };
    report["elapsed_ms"] = json!(started.elapsed().as_millis());
    let _ = done_tx.send(());
    println!("{report}");
    // Avoid an unbounded driver teardown after the measured probe completes.
    std::process::exit(exit);
}
