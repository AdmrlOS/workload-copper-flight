//! Minimal Bevy boundary shims; execute the real native exporter, not a copy.
extern crate self as bevy;
use std::{cell::{Cell, RefCell}, fs, io::Write, marker::PhantomData, ops::{Deref, DerefMut}, rc::Rc, time::Duration};
#[path="/project/patches/native_contract.rs"] mod native_contract;
pub mod render { pub mod renderer {
    pub struct RenderAdapterInfo { pub backend: &'static str, pub device_type: &'static str, pub name: String, pub vendor: u32 }
} }
struct Res<'a, T>(&'a T);
impl<T> Deref for Res<'_, T> { type Target = T; fn deref(&self) -> &T { self.0 } }
struct ResMut<'a, T>(&'a mut T);
impl<T> Deref for ResMut<'_, T> { type Target = T; fn deref(&self) -> &T { self.0 } }
impl<T> DerefMut for ResMut<'_, T> { fn deref_mut(&mut self) -> &mut T { self.0 } }
struct Physics;
struct Time<T>(Duration, PhantomData<T>);
impl<T> Time<T> { fn elapsed(&self) -> Duration { self.0 } fn elapsed_secs_f64(&self) -> f64 { self.0.as_secs_f64() } }
struct With<T>(PhantomData<T>);
struct Multicopter;
struct Query<T, F>(Option<T>, PhantomData<F>);
impl<T: Copy, F> Query<T, F> { fn single(&self) -> Result<T, ()> { self.0.ok_or(()) } }
struct Vector<const N: usize>([f32; N]);
impl<const N: usize> Vector<N> { fn to_array(&self) -> [f32; N] { self.0 } }
struct Position(Vector<3>); struct Rotation(Vector<4>); struct LinearVelocity(Vector<3>);
mod messages { pub enum FlightMode { Acro, Angle, PositionHold } }
struct SimRcInput { armed: bool, auto: bool, mode: messages::FlightMode }
struct Compute;
impl Compute { fn inference_backend(&mut self) -> Option<&'static str> { Some("cpu") } }
struct CopperState { compute: Compute, mcu_iteration_wall_us: u64, compute_iteration_wall_us: u64 }
mod sim_zed {
    use super::*;
    pub const ZED_SIM_WIDTH: u32 = 320; pub const ZED_SIM_HEIGHT: u32 = 240;
    #[derive(Clone)] pub struct Handle { pub mm: Rc<Vec<u16>>, pub calls: Rc<Cell<usize>> }
    impl Handle { pub fn with_inner<R>(&self, f: impl FnOnce(&Vec<u16>) -> R) -> R {
        self.calls.set(self.calls.get() + 1); f(&self.mm)
    } }
    pub struct SimZedFrameStore { pub frame: RefCell<Option<(u64, Handle)>> }
    impl SimZedFrameStore {
        pub fn observed_depth(&self) -> Option<(u64, Handle)> { self.frame.borrow().clone() }
        pub fn vitfly_prediction(&self) -> (u64, Option<[f32; 3]>) { (9, Some([1., 2., 3.])) }
    }
}
mod native_status {
// NATIVE_STATUS_IMPLEMENTATION
    pub(super) fn exercise() {
        let mut status = NativeStatus::from_env();
        let rc = SimRcInput { armed: true, auto: true, mode: messages::FlightMode::Angle };
        let store = sim_zed::SimZedFrameStore { frame: RefCell::new(None) };
        let calls = Rc::new(Cell::new(0));
        let mut copper = CopperState { compute: Compute, mcu_iteration_wall_us: 4, compute_iteration_wall_us: 8 };
        let mut tick = |step: u32| export_status(
            ResMut(&mut status), Res(&Time(Duration::from_secs_f64(step as f64 / 64.), PhantomData)), Res(&rc),
            Query(None, PhantomData), Res(&store), ResMut(&mut copper), None);
        let set_source = |seq, mm| { *store.frame.borrow_mut() = Some((seq, sim_zed::Handle { mm: Rc::new(mm), calls: calls.clone() })); };
        let due = || std::thread::sleep(Duration::from_millis(510));
        tick(0); // no default/reset raster
        set_source(41, vec![1000; 320*240]); due(); tick(1);
        tick(1); // same physics step must not create a pose or event
        set_source(42, vec![20000; 320*240]); tick(2); // wall cap: cached source 41
        assert_eq!(calls.get(), 1, "one existing CPU handle access per sampled source");
        due(); tick(3); // source 42
        due(); tick(4); // same source: no repeat raster or CPU access
        assert_eq!(calls.get(), 2);
        *store.frame.borrow_mut() = None; due(); tick(5); // clear both metadata and legacy thumbnail
        set_source(43, vec![20001; 320*240]); due(); tick(6); // invalid: absent
        let mut sparse = vec![0; 320*240]; sparse[0] = 1;
        set_source(44, sparse); due(); tick(7); // real full pixel outside legacy cell centers
        assert_eq!(calls.get(), 4, "legacy and full raster must share a single with_inner call");
    }
}
fn main() {
    unsafe { std::env::set_var("COPPER_FLIGHT_TELEMETRY", "/check/status.jsonl"); }
    native_status::exercise();
    print!("{}", fs::read_to_string("/check/status.jsonl").unwrap());
}
