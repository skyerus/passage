"""Blender product models of Paperwhite 11th gen and X4 Pro, from official references.

Not manufacturer CAD. Units are scaled for studio lighting; model dimensions
preserve 125 x 174 x 8.1 mm and 69 x 111 x 5.95 mm respectively.
"""
import argparse
import math
from pathlib import Path
import sys
import bpy
from mathutils import Vector


def material(name, color, roughness=.4, metallic=0):
    m=bpy.data.materials.new(name);m.diffuse_color=(*color,1);m.use_nodes=True
    bs=m.node_tree.nodes.get('Principled BSDF')
    bs.inputs['Base Color'].default_value=(*color,1)
    bs.inputs['Roughness'].default_value=roughness;bs.inputs['Metallic'].default_value=metallic
    return m


def shape(name,w,h,depth,radius,z,mat,parent):
    points=[]
    for cx,cy,start in [(w/2-radius,h/2-radius,0),(-w/2+radius,h/2-radius,90),(-w/2+radius,-h/2+radius,180),(w/2-radius,-h/2+radius,270)]:
        for j in range(9):
            angle=math.radians(start+j*90/8)
            points.append((cx+radius*math.cos(angle),cy+radius*math.sin(angle)))
    n=len(points);vertices=[(x,y,zz) for zz in (-depth/2,depth/2) for x,y in points]
    faces=[tuple(reversed(range(n))),tuple(range(n,2*n))]
    faces += [(i,(i+1)%n,(i+1)%n+n,i+n) for i in range(n)]
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(vertices,[],faces);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj)
    obj.location.z=z;obj.data.materials.append(mat);obj.parent=parent
    if depth>.009:
        bevel=obj.modifiers.new('Soft manufactured edges','BEVEL');bevel.width=min(depth*.2,.018);bevel.segments=4
        obj.modifiers.new('Weighted surface normals','WEIGHTED_NORMAL')
    return obj


def screen(name,w,h,y,z,path,parent):
    mat=material(name,(.8,.79,.72),.85)
    nodes=mat.node_tree.nodes;bs=nodes.get('Principled BSDF');tex=nodes.new('ShaderNodeTexImage')
    tex.image=bpy.data.images.load(str(path));tex.interpolation='Linear'
    mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Base Color'])
    mat.node_tree.links.new(tex.outputs['Color'],bs.inputs['Emission Color']);bs.inputs['Emission Strength'].default_value=.23
    verts=[(-w/2,-h/2,z),(w/2,-h/2,z),(w/2,h/2,z),(-w/2,h/2,z)]
    mesh=bpy.data.meshes.new(name);mesh.from_pydata(verts,[],[(0,1,2,3)]);mesh.update()
    obj=bpy.data.objects.new(name,mesh);bpy.context.collection.objects.link(obj);obj.parent=parent;obj.location.y=y
    mesh.materials.append(mat);uv=mesh.uv_layers.new()
    for i,coord in enumerate([(0,0),(1,0),(1,1),(0,1)]):uv.data[i].uv=coord


def build(name,assets):
    bpy.ops.object.empty_add();root=bpy.context.object;root.name=name
    black=material('Graphite polymer',(.021,.024,.025),.36)
    bezel=material('Flush charcoal bezel',(.026,.029,.03),.24)
    seam=material('Fine edge seam',(.007,.009,.009),.55)
    if name=='kindle':w,h,d=2.5,3.48,.162;sw,sh,sy=2.074,2.766,.116
    else:w,h,d=1.38,2.22,.119;sw,sh,sy=1.118,1.838,.064
    shape(name+' shell',w,h,d,.115 if name=='kindle' else .075,0,black,root)
    shape('Perimeter seam',w-.014,h-.014,.013,.10 if name=='kindle' else .065,d/2-.009,seam,root)
    shape('Face',w-.034,h-.034,.012,.10 if name=='kindle' else .062,d/2+.001,bezel,root)
    screen('Typeset e-ink display',sw,sh,sy,d/2+.011,assets/f'{name}-page.png',root)
    if name=='kindle':
        curve=bpy.data.curves.new('kindle wordmark','FONT');curve.body='kindle';curve.align_x='CENTER';curve.align_y='CENTER';curve.size=.142
        obj=bpy.data.objects.new('Kindle wordmark',curve);bpy.context.collection.objects.link(obj);obj.parent=root;obj.location=(0,-1.522,d/2+.014)
        curve.materials.append(material('Wordmark ink',(.15,.16,.165),.7))
        port=shape('USB-C',.22,.075,.008,.03,0,seam,root);port.rotation_euler.x=math.pi/2;port.location.y=-h/2-.004
        button=shape('Power button',.16,.045,.02,.02,0,bezel,root);button.rotation_euler.x=math.pi/2;button.location=(.56,-h/2-.007,0)
    else:
        bpy.ops.mesh.primitive_cylinder_add(vertices=64,radius=.080,depth=.003,location=(0,-.966,d/2+.016))
        touch=bpy.context.object;touch.name='Round touch sensor';touch.parent=root;touch.data.materials.append(material('Touch sensor',(.05,.052,.057),.55))
        for x,y,height in [(w/2+.012,.58,.17),(w/2+.012,.06,.32),(-w/2-.012,.06,.32)]:
            b=shape('Side control',.04,height,.065,.012,0,black,root);b.location.x=x;b.location.y=y
        gold=material('Pogo contacts',(.37,.25,.09),.28,.65)
        for x in (-.10,0,.10):
            bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=.025,location=(x,-h/2-.006,0))
            o=bpy.context.object;o.parent=root;o.scale=(1,.2,1);o.data.materials.append(gold)
    return root


def light(name,location,power,size,color,target=(0,0,0)):
    data=bpy.data.lights.new(name,'AREA');data.energy=power;data.shape='DISK';data.size=size;data.color=color
    o=bpy.data.objects.new(name,data);bpy.context.collection.objects.link(o);o.location=location
    o.rotation_euler=(Vector(target)-o.location).to_track_quat('-Z','Y').to_euler()


def main():
    p=argparse.ArgumentParser();p.add_argument('--output',type=Path,required=True);p.add_argument('--assets',type=Path,required=True)
    p.add_argument('--preview',action='store_true');p.add_argument('--frames',type=int,default=72)
    a=p.parse_args(sys.argv[sys.argv.index('--')+1:]);a.output.mkdir(parents=True,exist_ok=True)
    bpy.ops.wm.read_factory_settings(use_empty=True);s=bpy.context.scene;s.render.engine='BLENDER_EEVEE'
    s.render.resolution_x=760;s.render.resolution_y=1000;s.render.resolution_percentage=100
    s.render.image_settings.file_format='PNG';s.render.image_settings.color_mode='RGBA';s.render.film_transparent=True
    s.render.fps=30;s.world=bpy.data.worlds.new('Soft studio');s.world.use_nodes=True;s.world.node_tree.nodes['Background'].inputs[0].default_value=(.2,.23,.23,1);s.world.node_tree.nodes['Background'].inputs[1].default_value=.6
    s.view_settings.view_transform='AgX';s.view_settings.look='AgX - Medium High Contrast'
    if hasattr(s.eevee,'taa_render_samples'):s.eevee.taa_render_samples=32
    light('Large warm key',(-3,4,6),550,5,(1,.94,.82));light('Teal edge',(3,1,1),180,3,(.30,.8,.73));light('Soft fill',(-2,-4,4),160,4,(.8,.9,1));light('Top strip',(1,5,-1),240,3,(1,.92,.75))
    cam_data=bpy.data.cameras.new('Product camera');cam=bpy.data.objects.new('Product camera',cam_data);bpy.context.collection.objects.link(cam)
    cam.location=(0,0,8);cam.rotation_euler=(0,0,0);cam_data.type='ORTHO';cam_data.ortho_scale=4.15;s.camera=cam
    # A Blender camera looks down its local -Z axis; at positive Z this faces the products.
    for name in ['kindle','xteink']:
        root=build(name,a.assets);sub=a.output/name;sub.mkdir(exist_ok=True)
        # Normalize plate height; compositing restores the real relative dimensions.
        if name=='xteink':root.scale=(1.568,)*3
        n=1 if a.preview else a.frames
        for frame in range(n):
            theta=(frame/(a.frames-1))*2*math.pi
            root.rotation_euler=(math.radians(-8+5*math.cos(theta)),math.radians(21*math.sin(theta+.45)),math.radians(-4+3*math.sin(theta)))
            s.render.filepath=str(sub/f'{frame:04}.png');bpy.ops.render.render(write_still=True)
        for obj in list(root.children):bpy.data.objects.remove(obj,do_unlink=True)
        bpy.data.objects.remove(root,do_unlink=True)


if __name__=='__main__':main()
