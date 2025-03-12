try:
  import bpy
except Exception as e:
  print(f"Could not import bpy, due to {e}")
  print("""To fix, try:

  \tpip install bpy \
  OR
  \tuv add bpy \

""")
  exit()

from mathutils import Vector, Matrix
import math

import os
from argparse import ArgumentParser, ArgumentDefaultsHelpFormatter

def arguments():
  a = ArgumentParser(formatter_class=ArgumentDefaultsHelpFormatter)
  a.add_argument("--mesh")
  #a.add_argument("--original-mesh", required=True)
  a.add_argument("--output-image", "-o", default="tmp.png")

  a.add_argument("--width", default=1024, type=int, help="")
  a.add_argument("--height", default=1024, type=int, help="")
  a.add_argument("--final-render", action="store_true")
  a.add_argument("--hide-new", action="store_true")
  a.add_argument("--hide-original", action="store_true")
  a.add_argument("--flip-horizontal", action="store_true")
  a.add_argument("--samples", default=1024, type=int, help="Number of samples for rendering")

  a.add_argument("--cam-x", default=0, type=float, help="X of camera")
  a.add_argument("--cam-y", default=2, type=float, help="Y of camera")
  a.add_argument("--cam-z", default=-25, type=float, help="Z of camera")
  a.add_argument("--lookat-y", default=2, type=float, help="Y where camera is looking")
  a.add_argument("--lookat-z", default=0, type=float, help="Z where camera is looking")
  a.add_argument("--lookat-x", default=0, type=float, help="X where camera is looking")
  a.add_argument("--scale", default=12, type=float, help="Amount to scale mesh by")
  a.add_argument("--floor-y", default=0, type=float, help="Y of the floor")

  a.add_argument("--swap-xy", action="store_true", help="Swap X and Y coordinates")
  a.add_argument("--wireframe-thickness", default=0., type=float, help="Wireframe thickness")
  a.add_argument("--rot-z", default=45, type=float, help="Rotation of model")
  a.add_argument("--light-strength", default=4, type=float, help="Strength of light")
  a.add_argument("--flip-light", action="store_true", help="Flip light direction")
  a.add_argument("--light-z", type=float, help="Light z value", default=155)

  # rigid body arguments
  a.add_argument("--rigid-body", action="store_true", help="Add rigid body simulation with balls")
  a.add_argument("--balls", type=int, default=100, help="#balls in simulation")
  a.add_argument("--frame", default=-1, type=int, help="Frame to render")
  a.add_argument("--ball-height", default=8, type=float, help="Height of balls")
  a.add_argument("--ball-radius", default=0.2, type=float, help="Radius of ball")
  a.add_argument("--ball-extent", default=4, type=float, help="Extent balls can spawn around")
  a.add_argument("--ball-z-offset", default=0, type=float, help="Offset for balls on z-axis")
  a.add_argument("--debug-blend", default=None, type=str, help="If set, save to a temporary blend file")
  a.add_argument("--mesh-collider", action="store_true", help="Use a mesh collider for the input mesh")

  return a.parse_args()

def elemwise_minmax(vs):
  hx,hy,hz = lx,ly,lz = vs[0]
  for x,y,z in vs:
    lx = min(lx, x)
    ly = min(ly, y)
    lz = min(lz, z)
    hx = max(hx, x)
    hy = max(hy, y)
    hz = max(hz, z)

  # intentionally swap y and z below
  return Vector([lx,lz,ly]), Vector([hx, hz, hy])

def invisibleGround(location = (0,0,0), groundSize = 100, shadowBrightness = 0.7):
  # initialize a ground for shadow
  bpy.context.scene.cycles.film_transparent = True
  bpy.ops.mesh.primitive_plane_add(location = location, size = groundSize)
  try:
    bpy.context.object.is_shadow_catcher = True # for blender 3.X
  except:
    bpy.context.object.cycles.is_shadow_catcher = True # for blender 2.X

  # # set material
  ground = bpy.context.object
  mat = bpy.data.materials.new('MeshMaterial')
  ground.data.materials.append(mat)
  mat.blend_method = "BLEND"
  mat.use_nodes = True
  tree = mat.node_tree
  pbsdf = tree.nodes["Principled BSDF"]
  pbsdf.inputs['Transmission Weight'].default_value = shadowBrightness
  #pbsdf.inputs['Alpha'].default_value = 0.01

def add_wireframe(m, wireframe_thickness=0.01, target="Metallic"):
  if wireframe_thickness <= 0.: return

  if len(m.data.materials) == 0:
    mat = bpy.data.materials.new("MeshMaterial")
    m.data.materials.append(mat)
    m.active_material = mat
  for mat in m.data.materials:
    mat.use_nodes = True
    tree = mat.node_tree
    pbsdf = tree.nodes["Principled BSDF"]

    wire = tree.nodes.new(type="ShaderNodeWireframe")
    wire.inputs[0].default_value = wireframe_thickness

    neg = tree.nodes.new("ShaderNodeInvert")
    tree.links.new(wire.outputs["Fac"], neg.inputs[1])
    tree.links.new(neg.outputs[0], pbsdf.inputs[target])

def add_vertex_colors(m):
  if len(m.data.materials) == 0:
    mat = bpy.data.materials.new("MeshMaterial")
    m.data.materials.append(mat)
    m.active_material = mat
  for mat in m.data.materials:
    mat.use_nodes = True
    tree = mat.node_tree
    pbsdf = tree.nodes["Principled BSDF"]

    color_attrib = tree.nodes.new(type="ShaderNodeVertexColor")

    tree.links.new(color_attrib.outputs["Color"], pbsdf.inputs["Base Color"])

def set_transparent(m):
  for mat in m.data.materials:
    mat.blend_method = "BLEND"

    mat.use_nodes = True
    tree = mat.node_tree
    pbsdf = tree.nodes["Principled BSDF"]
    pbsdf.inputs['Transmission Weight'].default_value = 0.6
    pbsdf.inputs["Alpha"].default_value = 0.9
    pbsdf.inputs["Roughness"].default_value = 0.3

def center(o, origin=None):
  me = o.data
  mw = o.matrix_world
  l,h = elemwise_minmax([v.co for v in me.vertices])
  origin = origin or ((h+l)/2)

  mesh = bpy.data.objects[o.name]
  mesh.location = -origin
  return origin


def max_scale(os):
  scale = 0
  for o in os:
    me = o.data
    mw = o.matrix_world
    scale = max(scale, max(v.co.length for v in me.vertices))
  return scale

def rescale(os, scale=None, flip_h=False, swap_xy=False, rot_z=45, N=12):
  for o in os:
    me = o.data
    mw = o.matrix_world
    scale = scale or max(v.co.length for v in me.vertices)

    mesh = bpy.data.objects[o.name]
    mesh.scale = [N/scale, N/scale, (-N if flip_h else N)/scale]
    mesh.rotation_euler[2] = math.radians(rot_z)
    if swap_xy:
      mesh.rotation_euler[0] = math.radians(0)

def add_collision_sphere(i, args, mat):
    # add the camera x here so the balls are always aligned with the camera.
    x = math.sin(i * 1337) * args.ball_extent + args.cam_x
    y = math.cos(i * i * 9551) * args.ball_extent + args.ball_z_offset
    bpy.ops.mesh.primitive_uv_sphere_add(
      segments=8,ring_count=4,
      radius=args.ball_radius,calc_uvs=False, location=(x, y, args.ball_height)
    )
    bpy.ops.rigidbody.objects_add(type="ACTIVE")
    bpy.ops.object.material_slot_add()
    sph = bpy.context.active_object
    sph.material_slots[0].material = mat
    sph.color = (
      (1+math.sin(i * 997))/2,
      (1+math.cos(i * 48712))/2,
      (1+math.sin(i * i * 24351))/2,
      1
    )
    sph.rigid_body.collision_shape = "SPHERE"

def main():
  args = arguments()

  if args.rigid_body:
    bpy.ops.rigidbody.world_add()
    bpy.context.scene.frame_end = 1000
    bpy.context.scene.rigidbody_world.point_cache.frame_start = 0
    bpy.context.scene.rigidbody_world.point_cache.frame_end = 1000

  try:
    import blendertoolbox as bt
  except Exception as e:
    print(f"Could not import blendertoolbox, due to {e}")
    print("""To fix, try:

    \tpip install blendertoolbox \
    OR
    \tuv add blendertoolbox

    """)
    return;

  exposure = 1.5
  use_gpu = True
  bt.blenderInit(args.width, args.height, args.samples, exposure, use_gpu)
  if not args.final_render:
    bpy.context.scene.render.engine = 'BLENDER_EEVEE'
  else:
    bpy.context.scene.cycles.max_bounces = 1
    bpy.data.scenes[0].view_layers[0]['cycles']['use_denoising'] = 1


  assert(os.path.exists(args.mesh)), args.mesh
  is_ply = False
  if ".obj" in args.mesh:
    bpy.ops.wm.obj_import(filepath=args.mesh, use_split_groups=False)
  elif ".ply" in args.mesh:
    bpy.ops.wm.ply_import(filepath=args.mesh, up_axis="Y", forward_axis="Z")
    is_ply = True
  else: assert(False)

  if args.rigid_body:
    # make the input mesh passive
    bpy.ops.rigidbody.objects_add(type="PASSIVE")
    if args.mesh_collider:
      bpy.context.active_object.rigid_body.collision_shape = "MESH"


  new_mesh_obs = [o for o in bpy.context.scene.objects if o.type == "MESH"]
  ms = max_scale(new_mesh_obs)
  rescale(
    new_mesh_obs, ms, flip_h = args.flip_horizontal, swap_xy=args.swap_xy,
    N=args.scale, rot_z=args.rot_z,
  )
  bpy.context.view_layer.update()

  for o in new_mesh_obs: o.hide_render=args.hide_new

  if is_ply:
    for o in new_mesh_obs: add_vertex_colors(o)

  #for o in mesh_obs: set_transparent(o) # TEMPORARY LINE
  for o in new_mesh_obs: set_transparent(o)

  for o in new_mesh_obs: add_wireframe(o, args.wireframe_thickness)

  ## set invisible plane (shadow catcher)
  invisibleGround(location=(0,0,args.floor_y), shadowBrightness=0.03)

  ## set camera
  camLocation = (args.cam_x, args.cam_z, args.cam_y)
  lookAtLocation = (args.lookat_x,args.lookat_z,args.lookat_y)
  focalLength = 45
  cam = bt.setCamera(camLocation, lookAtLocation, focalLength)

  lightAngle = (6, -30, args.light_z if args.flip_light else -args.light_z)
  strength = args.light_strength
  shadowSoftness = 0.3
  sun = bt.setLight_sun(lightAngle, strength, shadowSoftness)


  if args.rigid_body:
    mat = bpy.data.materials.new("RandomColorMat")
    mat.use_nodes = True
    node_tree = mat.node_tree
    nodes = node_tree.nodes

    principled = next(n for n in nodes if isinstance(n, bpy.types.ShaderNodeBsdfPrincipled))

    info = nodes.new(type="ShaderNodeObjectInfo")
    info.location = principled.location - Vector((200, 0))
    links = node_tree.links
    links.new(info.outputs["Color"], principled.inputs["Base Color"])

    try:
      from tqdm import trange
    except Exception as e:
      print(f"Could not import bpy, due to {e}")
      print("""To fix, try:

        \tpip install bpy \
        OR
        \tuv add bpy \

      """)
      exit()

    # add some balls
    for i in trange(args.balls):
      add_collision_sphere(i, args, mat)
    print("[INFO]: Done adding collider spheres")

  if args.frame != -1:
    if args.rigid_body:
      bpy.ops.object.select_all(action='SELECT')
      area = [a for a in bpy.context.screen.areas if a.type=="VIEW_3D"][0]
      with bpy.context.temp_override(area=area):
          bpy.ops.rigidbody.bake_to_keyframes(frame_start=0, frame_end=args.frame+1)
      bpy.data.scenes["Scene"].render.use_motion_blur = True
      bpy.data.scenes["Scene"].render.motion_blur_shutter = 0.3
    bpy.context.scene.frame_set(args.frame)
  #bt.setLight_ambient((0.8, 0.8, 0.8, 0.8))

  ## set gray shadow to completely white with a threshold (optional but recommended)
  bt.shadowThreshold(alphaThreshold = 0.01, interpolationMode = 'CARDINAL')

  bpy.ops.object.shade_smooth() # Option1: Gouraud shading

  if args.debug_blend is not None:
    bpy.ops.wm.save_mainfile(filepath=args.debug_blend)

  bt.renderImage(args.output_image, cam)

if __name__ == "__main__": main()
