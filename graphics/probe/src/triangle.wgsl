@vertex
fn vs_main(@builtin(vertex_index) index: u32) -> @builtin(position) vec4<f32> {
    let positions = array<vec2<f32>, 3>(vec2(-0.75, -0.75), vec2(0.75, -0.75), vec2(0.0, 0.75));
    return vec4<f32>(positions[index], 0.25, 1.0);
}
