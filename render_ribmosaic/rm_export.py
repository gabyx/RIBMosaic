# #############################################################################
# AUTHOR BLOCK:
# #############################################################################
#
# RIB Mosaic RenderMan(R) IDE, see <http://sourceforge.net/projects/ribmosaic>
# by Eric Nathen Back aka WHiTeRaBBiT, 01-24-2010
# This script is protected by the GPL: Gnu Public License
# GPL - http://www.gnu.org/copyleft/gpl.html
#
# #############################################################################
# GPL LICENSE BLOCK:
# #############################################################################
#
# Script Copyright (C) Eric Nathen Back
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program.  If not, see <http://www.gnu.org/licenses/>.
#
# #############################################################################
# COPYRIGHT BLOCK:
# #############################################################################
#
# The RenderMan(R) Interface Procedures and Protocol are:
# Copyright 1988, 1989, 2000, 2005 Pixar
# All Rights Reserved
# RenderMan(R) is a registered trademark of Pixar
#
# #############################################################################
# COMMENT BLOCK:
# #############################################################################
#
# RIB export module to translate and write Blender scene data to RIB archives.
#
# This script is PEP 8 compliant
#
# Search TODO for incomplete code
# Search FIXME for improper code
# Search XXX for broken code
#
# #############################################################################
# END BLOCKS
# #############################################################################

import os
import sys
import shutil
import re
import signal
import stat
import subprocess
import queue
import tempfile
import gzip
import bpy
import mathutils
import math

# #### Global variables

MODULE = os.path.dirname(__file__).split(os.sep)[-1]
exec("from " + MODULE + " import rm_error")
exec("from " + MODULE + " import rm_context")
exec("from " + MODULE + " import rm_property")
exec("import " + MODULE + " as rm")

# if DEBUG_PRINT set true then each method with print its method name and important vars to console io
DEBUG_PRINT = True;

# ------------- RIB formatting Helpers -------------
# taken from Matt Ebb's Blender to 3Delight exporter

def rib_param_val(data_type, val):
    if data_type in ('float', 'integer', 'color', 'point'):
        vlen = 1
        
        if hasattr(val, '__len__'):
            vlen = len(val)
        
        if vlen > 1:
            return ' '.join([str(i) for i in val])
        else:
            return str(val)
    elif data_type == 'string':
        return '"%s"' % val

   
def rib_mat_str(m):
    return '[ %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f %f ]' % \
            (m[0][0], m[0][1], m[0][2], m[0][3], \
            m[1][0], m[1][1], m[1][2], m[1][3], \
            m[2][0], m[2][1], m[2][2], m[2][3], \
            m[3][0], m[3][1], m[3][2], m[3][3])


# ------------- Data Access Helpers -------------
# taken from Matt Ebb's Blender to 3Delight exporter

def is_visible_layer(scene, ob):

    for i in range(len(scene.layers)):
        if scene.layers[i] == True and ob.layers[i] == True:
            return True
    return False

def is_renderable(scene, ob):
    return (is_visible_layer(scene, ob) and not ob.hide_render) 
            
def get_renderables(scene):
    objects = []
    lights = []
    cameras = []

    for ob in scene.objects:
         if is_renderable(scene, ob):
             if ob.type in ['MESH', 'EMPTY']:
                 objects += [ob]
             elif ob.type in ['LAMP']:
                 lights += [ob]
             elif ob.type in ['CAMERA']:
                 cameras = [ob]
  
    return (objects, lights, cameras)

def is_subd_last(ob):
    return ob.modifiers and ob.modifiers[len(ob.modifiers)-1].type == 'SUBSURF'

def is_subd_displace_last(ob):
    if len(ob.modifiers) < 2: return False
    
    return (ob.modifiers[len(ob.modifiers)-2].type == 'SUBSURF' and
        ob.modifiers[len(ob.modifiers)-1].type == 'DISPLACE')

def is_subdmesh(ob):
    return (is_subd_last(ob) or is_subd_displace_last(ob))

def detect_primitive(ob):
#    rm = ob.renderman
    
#    if rm.primitive == 'AUTO':
    if ob.type == 'MESH':
        if is_subdmesh(ob):
            return 'SUBDIVISION_MESH'
        else:
            return 'POLYGON_MESH'
#    else:
#        return rm.primitive
 
def create_mesh(scene, ob, matrix=None):
    # 2 special cases to ignore:
    # subsurf last or subsurf 2nd last +displace last
    
    if is_subd_last(ob):
        ob.modifiers[len(ob.modifiers)-1].show_render = False
    elif is_subd_displace_last(ob):
        ob.modifiers[len(ob.modifiers)-2].show_render = False
        ob.modifiers[len(ob.modifiers)-1].show_render = False
    
    mesh = ob.to_mesh(scene, True, 'RENDER')    
    
    if matrix is not None:
        mesh.transform(matrix)

    return mesh

def render_get_resolution(r):
    xres= int(r.resolution_x*r.resolution_percentage*0.01)
    yres= int(r.resolution_y*r.resolution_percentage*0.01)
    return xres, yres


def render_get_aspect(r):
    xres, yres = render_get_resolution(r)
    
    xratio= xres*r.pixel_aspect_x/200.0
    yratio= yres*r.pixel_aspect_y/200.0

    if xratio > yratio:
        aspectratio= xratio/yratio
        xaspect= aspectratio
        yaspect= 1.0
    else:
        aspectratio= yratio/xratio;
        xaspect= 1.0;
        yaspect= aspectratio;
        
    return xaspect, yaspect, aspectratio




# The dummy pass class is used to provide default render pass settings if the scene does not provide one.
# During menu/panel draw/ and rendering context, it is not possible to modify RNA properties so for now
# we use the DummyPass as a hack to allow a default pass to be setup.
class DummyPass():
    name = "Beauty Pass"
    pass_enabled = True
    pass_type = 'BEAUTY'
    # Pass output properties
    pass_display_file = "Renders/@[EVAL:.current_frame:####]@@[EVAL:.pass_layer:]@.tif"
    pass_multilayer = False    
    pass_shadingrate = 1
    pass_eyesplits = 6
    pass_gridsize = 0
    pass_texturemem = 0
    # Pass camera properties
    pass_camera = ""
    pass_camera_group = False
    pass_camera_persp ='CAMERA'
    pass_camera_lensadj = 0.0
    pass_camera_nearclip = 0.005
    pass_camera_farclip = 500
    # Pass samples properties
    pass_samples_x = 0
    pass_samples_y = 0
    # Pass filter properties
    pass_filter = ""
    pass_width_x = 1
    pass_width_y = 1
    # Pass control properties
    pass_subpasses = 0
    pass_passid = 0
    # Pass tile passes properties
    pass_tile_x = 0
    pass_tile_y = 0
    pass_tile_index = 0
    # Pass sequence passes properties
    pass_seq_width = 0
    pass_seq_index = 0
    # Pass frame range properties
    pass_range_start = 0
    pass_range_end = 0
    pass_range_step = 0
    # Pass resolution properties
    pass_res_x = 0
    pass_res_y = 0
    # Pass aspect ratio properties
    pass_aspect_x = 0
    pass_aspect_y = 0
    # Pass scene filters properties
    pass_layerfilter = ""
    pass_panelfilter = ""
    pass_rib_string = ""


# #############################################################################
# EXPORT MANAGER CLASS
# #############################################################################

# #### Global object responsible for kicking off export process

class ExporterManager():
    """This class provides the entry point for the export manager
    responsible for generating and cleaning the export folders, initiating the
    export process for archives, shaders, ect and managing commands to be
    executed.
    """
    
    
    # #### Public attributes
    
    export_frame = 0 # Frame being exported
    export_scene = None # Scene being exported
    active_pass = None # The active pass
    export_directory = "" # Directory being exported to
    export_passes = [] # Pass collection being exported
    
    # Dictionary containing beauty pass display output info
    # passes = {'file':"", 'layer':"", 'multilayer':False}
    display_output = {'x':0, 'y':0, 'passes':[]}
    # Dictionary of all export path combinations
    export_paths = {'DIR':[],
                    'FRA':["Archives"],
                    'WLD':["Archives", "Worlds"],
                    'LAM':["Archives", "Lights"],
                    'OBJ':["Archives", "Objects"],
                    'GEO':["Archives", "Objects", "Geometry"],
                    'MAT':["Archives", "Objects", "Materials"],
                    'MAP':["Maps"],
                    'SHD':["Shaders"],
                    'TEX':["Textures"],
                    'RND':["Renders"],
                    'TMP':["Cache"]}
    # Dictionary of generated command objects
    command_scripts = {'OPTIMIZE':[],
                       'COMPILE':[],
                       'INFO':[],
                       'RENDER':[],
                       'POSTRENDER':[]}
    
    
    # #### Private attributes
    
    _exporting_scene = False # The target scene we are exporting
    _pass_ranges = [] # Store pass frame ranges for quick lookup
    
    
    # #### Private methods
    
    def _update_directory(self, scene=None):
        """Determines the export directory by resolving possible tokens and
        Blender relative paths from the scene property ribmosaic_export_path.
        Sets the public attributes export_directory and export_scene. Also
        initializes attributes that may be necessary for link resolution in
        export path.
        
        scene = The scene we are exporting and retrieving export directory from
        """
        if DEBUG_PRINT:
            print("ExportManager._update_directory")

        # Get active scene if not specified
        if not scene:
            if self.export_scene:
                scene = self.export_scene
            else:
                ### FIXME ###
                # can not modify context if scene data extracted from context
                scene = bpy.context.scene
        
        # If no active scene try grabbing the first one
        if not scene:
            scene = bpy.data.scenes[0]
        
        if scene:
            # Insure RIB Mosaic passes are set
            ### FIXME ###
            # can not modify context if scene data extracted from context
            rp = scene.ribmosaic_passes
            pl = len(rp.collection)
            ai = rp.active_index

            if DEBUG_PRINT:
                print("scene.name: " + scene.name)
                print("number of passes: ", pl)
                print("active pass index: ", ai)
            
            #if not pl:
            #    rp.collection.add().name = "Beauty Pass"
            #    pl = 1
            
            #if ai > pl - 1:
            #    rp.active_index = pl - 1
            #    ai = pl - 1
            
            self._pass_ranges = []
            self.export_passes = rp.collection
            if rp.collection and ai:
                self.active_pass = rp.collection[ai]
            else: 
                # make a new dummy pass list
                self.export_passes = [DummyPass()]
                self.active_pass = self.export_passes[0] 
            
            # Store frame ranges for each pass for quick look up later
            for p in self.export_passes:
                # Determine frame range of pass
                if p.pass_range_start:
                    start = p.pass_range_start
                else:
                    start = scene.frame_start
                
                if p.pass_range_end:
                    end = p.pass_range_end
                else:
                    end = scene.frame_end
                
                if p.pass_range_step:
                    step = p.pass_range_step
                else:
                    step = scene.frame_step
                
                self._pass_ranges.append(range(start, end + 1, step))
            
            # Resolve export directory
            ec = rm_context.ExportContext(pointer_datablock=scene)
            path = scene.ribmosaic_export_path
            
            if path:
                path = ec._resolve_links(path, "Export Directory Property")
                path = os.path.realpath(bpy.path.abspath(path)) + os.sep
                del ec
            else:
                raise rm_error.RibmosaicError("No export directory specified, "
                                     "see \"Scene->Export Options->Export Path\"")
        else:
            raise rm_error.RibmosaicError("Cannot determine active scene "
                                          "for export directory")
        
        # Make sure working directory points to export directory
        try:
            os.chdir(path)
        except:
            pass
        
        self.export_scene = scene
        self.export_directory = path
                
    
    
    # #### Public methods
    
    def prepare_export(self, active_scene=None,
                       clean_paths=['DIR'],
                       purge_paths=['TMP'],
                       shader_library=""):
        """Prepares the export attributes and folders for a new export process.
        Should be called before any other public export_manager methods.
        
        active_scene = The scene we are exporting and retrieving properties from
        clean_paths = Remove all files in specified self.export_paths dict keys
        purge_paths = Remove everything in specified self.export_paths dict keys
        shader_library = Pipeline of shader library to prepare
        """
        
        if DEBUG_PRINT:
            print("ExportManager.prepare_directory")

        if not bpy.data.is_dirty:
            self._update_directory(active_scene)
            
            try:
                # If active scene assume we are preparing for export
                if active_scene and not shader_library:
                    # If in interactive mode NEVER clean or purge paths
                    if active_scene.ribmosaic_interactive:
                        activepass = True
                        purgerib = False
                        purgeshd = False
                        purgetex = False
                        clean_paths = []
                        purge_paths = []
                    else:
                        activepass = active_scene.ribmosaic_activepass
                        purgerib = active_scene.ribmosaic_purgerib
                        purgeshd = active_scene.ribmosaic_purgeshd
                        purgetex = active_scene.ribmosaic_purgetex
                        clean_paths = list(clean_paths)
                        purge_paths = list(purge_paths)
                    
                    # Add archive paths to clean if purging RIBs
                    if purgerib and not activepass:
                        for p in ['FRA', 'WLD', 'LAM', 'OBJ', 'GEO', 'MAT']:
                            if not p in clean_paths:
                                clean_paths.append(p)
                    
                    # Add shader path to purge if purging shaders
                    if purgeshd:
                        if not 'SHD' in purge_paths:
                            purge_paths.append('SHD')
                    
                    # Add texture path to purge if purging textures
                    if purgetex:
                        if not 'TEX' in purge_paths:
                            purge_paths.append('TEX')
                
                # Check that export folders exist and clean or purge them
                for p in self.export_paths:
                    path = self.export_directory + os.sep.join(self.export_paths[p])
                    
                    if not os.path.exists(path):
                        os.makedirs(path)
                    else:
                        purge = p in purge_paths
                        clean = p in clean_paths
                        
                        if purge or clean:
                            for f in os.listdir(path):
                                p = path + os.sep + f
                                
                                if os.path.isfile(p):
                                    os.remove(p)
                                elif purge and os.path.isdir(p):
                                    shutil.rmtree(p)
                
                # Reset exporter attributes
                self.export_frame = 0
                self.display_output = {'x':0, 'y':0, 'passes':[]}
                
                # Be sure previous commands are closed and cleared
                for k in self.command_scripts:
                    for c in self.command_scripts[k]:
                        c.close_archive()
                        c.terminate_command()
                    
                    self.command_scripts[k] = []
                
                # Make sure working directory points to export directory
                try:
                    os.chdir(self.export_directory)
                except:
                    pass
            except:
                raise rm_error.RibmosaicError("Could not prepare export directory, "
                                              "check console for details",
                                              sys.exc_info())
        else:
            raise rm_error.RibmosaicError("Blend must be saved before "
                                          "it can be exported")
    
    def export_shaders(self, render_object=None, shader_library=""):
        """Exports shaders for all pipelines (including Blender's text editor
        shaders as a virtual pipeline). Also generates both compile and info
        command objects and loads them in the command_scripts attribute.
        Shader libraries are only processed individually if specified.
        
        render_object = The RenderEngine object currently exporting from
        shader_library = Pipeline of shader library to process exclusively
        """
        if DEBUG_PRINT:
            print("ExportManager.export_shaders")
        
        # Gather available command panels
        purge = self.export_scene.ribmosaic_purgeshd
        compile_commands = rm.pipeline_manager.list_panels("command_panels",
                                                           type='COMPILE')
        info_commands = rm.pipeline_manager.list_panels("command_panels",
                                                        type='INFO')
        
        # Setup generic export context object
        ec = rm_context.ExportContext(None, self.export_scene, self.active_pass)
        ec.root_path = self.export_directory
        ec.context_window = 'SCENE'
        ec.pointer_render = render_object
        
        # Build pipelines list to process
        if shader_library:
            pipelines = [shader_library]
        else:
            pipelines = rm.pipeline_manager.list_pipelines()
            pipelines.append("Text_Editor")
        
        # If in interactive mode DO NOT export shaders
        if self.export_scene.ribmosaic_interactive:
            pipelines = []
        
        # Create folders, export sources and generate command scripts
        for p in pipelines:
            libraries = []
            
            # Virtual Text_Editor pipeline is always enabled otherwise check
            if p == "Text_Editor":
                libraries.append("xml")
            elif p == shader_library:
                lib = rm.pipeline_manager.get_attr(ec, p, "library", False, "")
                
                if lib:
                    libraries.append(lib)
            elif eval(rm.pipeline_manager.get_attr(ec, p, "enabled", False, "True")):
                libraries.append("xml")
            
            # Only export shaders if pipeline contains shader libraries
            for library in libraries:
                is_shaders = False
                
                # Export shader sources
                if library == "xml":
                    compile = True
                    info = self.export_scene.ribmosaic_compileshd
                    
                    # Setup shader paths to be relative from export directory
                    path = "." + os.sep + \
                           os.sep.join(self.export_paths['SHD']) + \
                           os.sep + p + os.sep
                    ec.target_path = path
                    ec.target_name = ""
                    
                    try:
                        os.makedirs(path)
                    except:
                        pass
                    
                    # Export sources in Blender's text editor
                    if p == "Text_Editor":
                        for t in bpy.data.texts:
                            if t.filepath:
                                name = os.path.basename(t.filepath)
                            else:
                                name = t.name
                            
                            ext = os.path.splitext(name)[1]
                            
                            # Only export source code
                            if ext == ".sl" or ext == ".h":
                                if purge:
                                    f = open(path + name, 'w')
                                    f.write(t.as_string())
                                    f.close()
                                
                                is_shaders = True
                    # Export sources in XML data   
                    else:
                        for e in rm.pipeline_manager.list_elements(p + \
                                 "/shader_sources"):
                            xmlp = p + "/shader_sources/" + e
                            name = rm.pipeline_manager.get_attr(ec, xmlp,
                                                             "filepath", False)
                            name = os.path.basename(name)
                            
                            if name:
                                if purge:
                                    source = rm.pipeline_manager.get_text(ec, xmlp)
                                    f = open(path + name, 'w')
                                    f.write(source)
                                    f.close()
                                
                                is_shaders = True
                            else:
                                raise rm_error.RibmosaicError("Attribute error in " + \
                                                xmlp + ", must specify filepath")
                    
                    # If no shaders exported remove empty directory
                    if not is_shaders:
                        try:
                            os.rmdir(path)
                        except:
                            pass
                # Setup for library processing (only create compile and info commands)
                else:
                    # Always setup library path to be absolute
                    path = os.path.realpath(bpy.path.abspath(library)) + os.sep
                    is_shaders = True
                    
                    if path:
                        compile = eval(rm.pipeline_manager.get_attr(ec, p, "compile",
                                                                False, "False"))
                        
                        # Only check for building info if export option is set
                        if self.export_scene.ribmosaic_compileshd:
                            info = eval(rm.pipeline_manager.get_attr(ec, p, "build",
                                                                False, "False"))
                        else:
                            info = False
                        
                        ec.target_path = path
                        ec.target_name = ""
                    else:
                        raise rm_error.RibmosaicError("Pipeline library incorrect for " + p)
                
                # generate command scripts for pipelines with shaders
                if is_shaders:
                    ec.current_library += 1 # Increment shader library index
                    ec.current_command = 0 # Reset command index
                    
                    for c in compile_commands:
                        # Setup command panel context from xmlpath
                        segs = c.split("/")
                        ec.context_pipeline = segs[0]
                        ec.context_category = segs[1]
                        ec.context_panel = segs[2]
                        
                        # Only export enabled command panels
                        if compile and ec._panel_enabled():
                            ec.current_command += 1
                            name = ec._resolve_links( \
                                   "COMPILE_S@[EVAL:.current_library:#####]@"
                                   "_C@[EVAL:.current_command:#####]@")
                            path = "." + os.sep
                            
                            try:
                                s = ExporterCommand(ec, c, False, path, name)
                                s.build_code("begin")
                                s.build_code("middle")
                                s.build_code("end", True)
                            except:
                                s.close_archive()
                                raise rm_error.RibmosaicError("Failed to build command " + \
                                                              name, sys.exc_info())
                            
                            self.command_scripts['COMPILE'].append(s)
                    
                    ec.current_command = 0 # Reset command index
                    
                    for c in info_commands:
                        # Setup command panel context from xmlpath
                        segs = c.split("/")
                        ec.context_pipeline = segs[0]
                        ec.context_category = segs[1]
                        ec.context_panel = segs[2]
                        
                        # Only export enabled command panels
                        if info and ec._panel_enabled():
                            ec.current_command += 1
                            name = ec._resolve_links( \
                                   "INFO_S@[EVAL:.current_library:#####]@"
                                   "_C@[EVAL:.current_command:#####]@")
                            path = "." + os.sep
                            
                            try:
                                s = ExporterCommand(ec, c, True, path, name)
                            except:
                                s.close_archive()
                                raise rm_error.RibmosaicError("Failed to build command " + \
                                                              name, sys.exc_info())
                            
                            self.command_scripts['INFO'].append(s)
        
        del ec
    
    def export_textures(self, render_object=None):
        """...
        
        render_object = The RenderEngine object currently exporting from
        """
        if DEBUG_PRINT:
            print("ExportManager.export_textures")
        
        purge = self.export_scene.ribmosaic_purgetex
        optimize = self.export_scene.ribmosaic_optimizetex
        interactive = self.export_scene.ribmosaic_interactive
        
        if optimize and not interactive:
            pass
    
    def export_rib(self, render_object=None):
        """Entry point to RIB exporting process for all passes under current
        frame. This creates a root export context object and populates it with
        information from export_scene and active passes. Then an ExportPass object
        is initialized from the export context object, automatically initializing
        archives and inheriting new objects down the scene's object tree. This
        method is meant to work with the RenderEngine.render() method to produce
        all archives and commands necessary to render one frame at a time while
        producing a complete archive package that can be run later from console.
        It also produces RIB and commands per frame so they can be more easily
        distributed on a farm.
        
        render_object = The RenderEngine object currently exporting from
        """
        if DEBUG_PRINT:
            print("ExportManager.export_rib")
        
        # Setup global information
        self._exporting_scene = True
        command_path = "." + os.sep
        target_path = "." + os.sep + "Archives" + os.sep
        render_commands = rm.pipeline_manager.list_panels("command_panels", \
                                                       type='RENDER')
        postrender_commands = rm.pipeline_manager.list_panels("command_panels", \
                                                           type='POSTRENDER')
        
        # Setup scene information
        f = self.export_scene.frame_current
        r = self.export_scene.render
        x = int(r.resolution_x * r.resolution_percentage * 0.01)
        y = int(r.resolution_y * r.resolution_percentage * 0.01)
        export_rib = self.export_scene.ribmosaic_exportrib
        only_active = self.export_scene.ribmosaic_activepass
        
        self.export_frame = f
        self.display_output = {'x':x, 'y':y, 'passes':[]}
        
        # If in interactive mode ALWAYS export archives
        if self.export_scene.ribmosaic_interactive:
            export_rib = True
            only_active = True
        
        # Process current scene's RenderMan passes
        for i, p in enumerate(self.export_passes):
            # Make sure pass is enabled and within frame ranges
            if p.pass_enabled and f in self._pass_ranges[i]:
                # Setup export context state per pass
                ec = rm_context.ExportContext(None, self.export_scene, p)
                ec.root_path = self.export_directory
                ec.pointer_render = render_object
                ec.current_pass = i + 1
                ec.current_frame = f
                ec.dims_resx = x
                ec.dims_resy = y
                target_name = ec._resolve_links("P@[EVAL:.current_pass:#####]@"
                                          "_F@[EVAL:.current_frame:#####]@.rib")
                
                # Add to display list if a beauty pass
                if ec.pass_type == 'BEAUTY':
                    display_output = ec._resolve_links(ec.pass_output)
                    self.display_output['passes'].append({'file':display_output,
                                                'layer':ec.pass_layer,
                                                'multilayer':ec.pass_multilayer})
                
                # Do not build RIB if disabled in export options
                if export_rib and (not only_active or p == self.active_pass):
                    try:
                        pa = ExportPass(ec, target_path, target_name)
                        pa.export_rib()
                        del pa
                    except:
                        pa.close_archive()
                        del pa
                        raise rm_error.RibmosaicError("Failed to build RIB " + \
                                                      target_name, sys.exc_info())
                
                # Build RENDER command scripts
                for c in render_commands:
                    segs = c.split("/")
                    ec.context_pipeline = segs[0]
                    ec.context_category = segs[1]
                    ec.context_panel = segs[2]
                    ec.target_path = target_path
                    ec.target_name = target_name
                    
                    # Only export enabled command panels
                    if ec._panel_enabled():
                        ec.current_command += 1
                        name = ec._resolve_links("RENDER_P@[EVAL:.current_pass:#####]@"
                                                 "_F@[EVAL:.current_frame:#####]@"
                                                 "_C@[EVAL:.current_command:#####]@")
                        
                        try:
                            s = ExporterCommand(ec, c, False, command_path, name)
                            s.build_code("begin")
                            s.build_code("middle")
                            s.build_code("end", True)
                        except:
                            s.close_archive()
                            raise rm_error.RibmosaicError("Failed to build command " + \
                                                          name, sys.exc_info())
                        
                        self.command_scripts['RENDER'].append(s)
                
                # Build POSTRENDER command scripts
                for c in postrender_commands:
                    segs = c.split("/")
                    ec.context_pipeline = segs[0]
                    ec.context_category = segs[1]
                    ec.context_panel = segs[2]
                    ec.target_path = ""
                    ec.target_name = ""
                    
                    # Only export enabled command panels
                    if ec._panel_enabled():
                        ec.current_command += 1
                        name = ec._resolve_links("RENDER_P@[EVAL:.current_pass:#####]@"
                                                 "_F@[EVAL:.current_frame:#####]@"
                                                 "_C@[EVAL:.current_command:#####]@")
                        
                        try:
                            s = ExporterCommand(ec, c, False, command_path, name)
                            s.build_code("begin")
                            s.build_code("middle")
                            s.build_code("end", True)
                        except:
                            s.close_archive()
                            raise rm_error.RibmosaicError("Failed to build command " + \
                                                          name, sys.exc_info())
                        
                        self.command_scripts['POSTRENDER'].append(s)
                
                del ec
        
        self._exporting_scene = False
    
    def execute_commands(self):
        """Executes any accumulated commands in the command_scripts attribute.
        This method automatically checks the render export options to determine
        if each command type should be executed and clears the commands from
        command_scripts once executed.
        """
        if DEBUG_PRINT:
            print("ExportManager.execute_commands")
        
        c = self.export_scene.ribmosaic_compileshd
        o = self.export_scene.ribmosaic_optimizetex
        r = self.export_scene.ribmosaic_renderrib
        
        # If in interactive mode ALWAYS render archives
        if self.export_scene.ribmosaic_interactive:
            r = True
        
        # Create one root shell script to rule them all
        root = ExporterCommand(None, "", False, "." + os.sep, "START.sh.bat", 'a')
        
        try:
            # Cycle through commands of each type and execute
            for t in ['OPTIMIZE', 'COMPILE', 'INFO', 'RENDER', 'POSTRENDER']:
                for s in self.command_scripts[t]:
                    # Be sure command is enabled in scene export options
                    if ((t == 'RENDER' or t == 'POSTRENDER') and r) or \
                            ((t == 'COMPILE' or t == 'INFO') and c) or \
                            (t == 'OPTIMIZE' and o):
                        s.execute_command()
                    
                    if t != 'INFO':
                        # Write all but info commands to root shell script
                        root.write_text("." + os.sep + s.archive_name + "\n")
                
                # Clear executed command objects
                if not self.export_scene.ribmosaic_interactive:
                    self.command_scripts[t] = []
        except:
            pass
        
        # Clean up
        root.close_archive()




# #############################################################################
# EXPORTER OBJECT CLASSES
# #############################################################################

# #### Super class for all exporter objects
 
class ExporterArchive(rm_context.ExportContext): 
    """This base class provides common functionality for creating archives of
    various types, maintaining the archive and cache file objects and managing
    object registration for threading.
    """
    
    
    # #### Public attributes
    
    is_file = True # To distinguish a file object from a export object
    is_root = True # To determine if this is the root archive
    is_gzip = False # Set to handle file as gzipped
    is_exec = False # Set to handle file as executable
    
    
    # #### Private attributes
    
    _queque_mode = 0
    _queque_priority = 0
    
    _pointer_file = None
    _pointer_cache = None
    _archive_regexes = []
    _target_regexes = []
    
    
    # #### Private methods
    
    def __init__(self, export_object=None, archive_path="", archive_name=""):
        """Initialize attributes using export_object and parameters.
        
        export_object = Any object subclassed from ExportContext
        archive_path = Path to save archive to (from export_object otherwise)
        archive_name = Name to save archive as (from export_object otherwise)
        """
        
        rm_context.ExportContext.__init__(self, export_object)
        
        # If export object is already a file object pass its attributes
        if getattr(export_object, "is_file", False):
            self.is_root = False # If inherited then not root file
            
            self.is_gzip = getattr(export_object, "is_gzip",
                                        self.is_gzip)
            self.is_exec = getattr(export_object, "is_exec",
                                        self.is_exec)
            self.archive_path = getattr(export_object, "archive_path",
                                        self.archive_path)
            self.archive_name = getattr(export_object, "archive_name",
                                        self.archive_name)
            self._queque_mode = getattr(export_object, "_queque_mode",
                                        self._queque_mode)
            self._queque_priority = getattr(export_object, "_queque_priority",
                                        self._queque_priority)
            self._pointer_file = getattr(export_object, "_pointer_file",
                                        self._pointer_file)
            self._pointer_cache = getattr(export_object, "_pointer_cache",
                                        self._pointer_cache)
            self._archive_regexes = getattr(export_object, "_archive_regexes",
                                        self._archive_regexes)
            self._target_regexes = getattr(export_object, "_target_regexes",
                                        self._target_regexes)
        else:
            # Insure each object has a unique list
            self._archive_regexes = list(self._archive_regexes)
            self._target_regexes = list(self._target_regexes)
        
        # If archive path specified use it
        if archive_path:
            self.archive_path = archive_path
        
        # If archive name specified use it
        if archive_name:
            self.archive_name = archive_name
    
    
    # #### Public methods
    
    def open_archive(self, gzipped=None, execute=None, mode='w'):
        """Opens a new archive for writing using archive_path and archive_name.
        
        gzippped = Create archive using gzip compression (True/False)
        execute = Create archive with executable permissions (True/False)
        mode = File 'r', 'a', 'w' open mode (gzipped is always binary mode)
        """
        if DEBUG_PRINT:
            print("ExporterArchive.open_archive()")
        
        if gzipped is not None:
            self.is_gzip = gzipped
        
        if execute is not None:
            self.is_exec = execute
        
        if self.archive_name:
            filepath = self.archive_path + self.archive_name
            
            try:
                if self.is_gzip:
                    self._pointer_file = gzip.open(filepath, mode)
                else:
                    self._pointer_file = open(filepath, mode)
                
                if self.is_exec:
                    os.chmod(filepath, stat.S_IRUSR | stat.S_IWUSR | stat.S_IXUSR | \
                                       stat.S_IRGRP | stat.S_IXGRP | \
                                       stat.S_IROTH | stat.S_IXOTH)
                
                self.is_root = True # If creating a new archive this object is root
            except:
                raise rm_error.RibmosaicError("Could not open archive \"" + filepath + \
                                              "\" for '" + mode + "'", sys.exc_info())
        else:
            raise rm_error.RibmosaicError("Archive's path and name must be specified")
    
    def close_archive(self):
        """Close archive object for writing and apply regex objects"""
        
        if DEBUG_PRINT:
            print("ExporterArchive.close_archive()")

        # Only allow root object to close file
        if self.is_root:
            # Close down any cache pointers
            if self._pointer_cache:
                self._pointer_cache.close()
                self._pointer_cache = None
            
            # Close down any archive pointers
            if self._pointer_file:
                try:
                    self._pointer_file.close()
                    self._pointer_file = None
                except:
                    raise rm_error.RibmosaicError("Cannot close archive", sys.exc_info())
                
                # Apply regex objects to archive
                if self._archive_regexes:
                    try:
                        # Get text from archive
                        self.open_archive(mode='r')
                        text = self._pointer_file.read()
                        self._pointer_file.close()
                        
                        # Get each regexes element
                        for xmlpath in self._archive_regexes:
                            # Get each regex sub element in regexes
                            for element in rm.pipeline_manager.list_elements(xmlpath):
                                regpath = xmlpath + "/" + element
                                
                                # Get regex attributes
                                regex = rm.pipeline_manager.get_attr(self, regpath,
                                                            "regex", True, "")
                                replace = rm.pipeline_manager.get_attr(self, regpath,
                                                            "replace", True, "")
                                matches = rm.pipeline_manager.get_attr(self, regpath,
                                                            "matches", True, "0")
                                
                                # If gzipped setup binary regex
                                if self.is_gzip:
                                    regex = bytes(regex.encode())
                                    replace = bytes(replace.encode())
                                
                                # Apply regex to text
                                text = re.sub(regex, replace, text,
                                              int(matches), re.MULTILINE)
                        
                        # Write text back to archive
                        self.open_archive(mode='w')
                        self.write_text(text)
                        self._pointer_file.close()
                        
                        self._pointer_file = None
                    except:
                        rm_error.RibmosaicError("Cannot apply regex to archive",
                                                sys.exc_info())
    
    def write_text(self, text="", close=False):
        """Writes text to this archive's open file handle. Also properly writes
        text as either encoded binary or text mode according to is_gzip attribute.
        
        text = The text to write (can contain escape characters)
        close = If true closes script archive when complete
        """
        if DEBUG_PRINT:
            print("ExporterArchive.write_text()")
        
        if text:
            if self.current_indent > 0:
                text = " ".rjust(self.current_indent * 4) + text    
            
            if self._pointer_file:
                if self.is_gzip:
                    self._pointer_file.write(text.encode())
                else:
                    self._pointer_file.write(text)
            else:
                raise rm_error.RibmosaicError("Archive already closed, cannot write text")
        
        if close:
            self.close_archive()
    
    def write_code(self, xmlpath="", close=False):
        """Build and write element text code to archive. Also uses the
        element's "target" attribute to set a target path/file including the
        *.ext wildcard for multiple targets by extension. The target path/file
        is searched and each match is set to the export context's "target_path",
        "target_name" attributes (for link resolution in panel code), then the
        code within the element is built and written.
        
        element = The code text element to build
        close = If true closes script archive when complete
        """

        if DEBUG_PRINT:
            print("ExporterArchive.write_code()")
        
        target = rm.pipeline_manager.get_attr(self, xmlpath, "target", False)
        
        for t in self.list_targets(target):
            if t[0]:
                self.target_path = t[0]
            
            if t[1]:
                self.target_name = t[1]
            
            text = rm.pipeline_manager.get_text(self, xmlpath)
            
            self.write_text(text)
        
        if close:
            self.close_archive()
    
    def list_targets(self, target=""):
        """Searches target path/file.ext and returns a list of matches. If path
        is not specified export context target_path is used, if no file then
        export context target_name is used. If file uses the * operator then
        all files matching extension are listed.
        
        target = path/file.ext of target to search or path/*.ext for wildcard
        returns = list of matching target (path, file) or "" if no matches
        """

        if DEBUG_PRINT:
            print("ExporterArchive.list_targets()")
        
        # Populate files list according to target
        if target:
            target = target = os.path.split(target)
            
            if target[0]:
                path = target[0] + os.sep
            else:
                path = self.target_path
            
            if target[1].startswith("*"):
                if path:
                    try:
                        matches = [(path, f) for f in os.listdir(path) \
                                 if os.path.splitext(f)[1] == target[1][1:]]
                    except:
                        raise rm_error.RibmosaicError("Cannot find target directory/file, "
                                                      "check export and/or library paths")
                else:
                    matches = [("", "")]
            else:
                if target[1]:
                    matches = [(path, target[1])]
                else:
                    matches = [(path, self.target_name)]
        else:
            matches = [("", "")]
        
        return matches
    
    def add_regexes(self, xmlpath):
        """Add specified xmlpath of a regexes XML element onto this archives regex
        list. All regex sub elements will be evaluated into regular expressions
        and applied to this archive's text when close_archive() is issued.
        The path is either added to the archive or target list depending on its
        target element attribute.
        
        xmlpath = XML pipeline path to a panels regexes element
        """

        if DEBUG_PRINT:
            print("ExporterArchive.add_regexes()")
        
        if xmlpath:
            subelements = rm.pipeline_manager.list_elements(xmlpath)
            
            if subelements:
                target = rm.pipeline_manager.get_attr(self, xmlpath, "target", False)
                
                if target:
                    self._target_regexes.append(xmlpath)
                else:
                    self._archive_regexes.append(xmlpath)
    
    def apply_regextargets(self):
        """Applies target based regexes from self._target_regexes. This works by
        building a list of target files from each regexes target attribute and
        applying the regex to each.
        """

        if DEBUG_PRINT:
            print("ExporterArchive.apply_regextargets()")
        
        # Get each target regex xmlpath
        for xmlpath in self._target_regexes:
            target = rm.pipeline_manager.get_attr(self, xmlpath, "target", False)
            
            for t in [t for t in self.list_targets(target) if t[1]]:
                self._test_break()
                
                # Open file as new archive initialized from self
                archive = ExporterArchive(self, t[0], t[1])
                
                # Apply target regex to archive regex
                archive._archive_regexes = [xmlpath]
                archive._target_regexes = []
                
                # Open and close archive to apply regex
                archive.open_archive(mode='r')
                archive.close_archive()

    def riFrameBegin(self):
        self.write_text('FrameBegin %s\n' % self.current_rmframe)
        self.inc_indent()
        
    def riFrameEnd(self):
        self.dec_indent()
        self.write_text('FrameEnd\n')

    def riWorldBegin(self):
        self.write_text('WorldBegin\n')
        self.inc_indent()
        
    def riWorldEnd(self):
        self.dec_indent()
        self.write_text('WorldEnd\n')

    def riAttributeBegin(self):
        self.write_text('AttributeBegin\n')
        self.inc_indent()

    def riAttributeEnd(self):
        self.dec_indent()
        self.write_text('AttributeEnd\n')
        
    def riIlluminate(self, idx, state=1):
        self.write_text('Illuminate "%s" %s\n' % (idx, state));


# #### Pipeline panel sub classes (all derived from ExporterArchive)

class ExporterCommand(ExporterArchive):
    """This subclass represents a shell script created from the data in a xmlpath
    of a pipeline command panel. It provides all necessary public methods and
    attributes for creating, building and executing a shell script from XML source.
    """
    
    
    # #### Public attributes
    
    command_xmlpath = "" # XML path to command panel this object represents
    command_process = None # Pointer to Popen process
    delay_build = False # Delay building command until execution
    
    
    # #### Private methods
    
    def __init__(self, export_object=None, command_xmlpath="", delay_build=False,
                       archive_path="", archive_name="", archive_mode="w"):
        """Initialize attributes using export_object and command_xmlpath as well
        as create shell script file ready for writing.
        
        export_object = Any object subclassed from ExportContext
        command_xmlpath = XML pipeline path to command to process
        archive_path = Path to save script to (otherwise export_object.archive_path)
        archive_name = Name to save script as (otherwise export_object.archive_name)
        archive_mode = File open mode ('r', 'a', 'w')
        """
        
        self.command_xmlpath = command_xmlpath
        self.delay_build = delay_build
        
        # Append file extension from command panel extension attribute
        if command_xmlpath and archive_name:
            archive_name += rm.pipeline_manager.get_attr(self, command_xmlpath,
                                                          "extension", False)
        
        ExporterArchive.__init__(self, export_object, archive_path, archive_name)
        
        # Automatically add regexes and create archive
        if command_xmlpath:
            self.add_regexes(command_xmlpath + "/regexes")
        
        self.open_archive(execute=True, mode=archive_mode)
    
    
    # #### Public methods
    
    def terminate_command(self):
        """Terminate the currently running process"""

        if DEBUG_PRINT:
            print("ExporterCommand.terminate_command()")
        
        try:
            try: # Try it unix style
                os.killpg(self.command_process.pid, signal.SIGTERM)
            except: # Try it windows style
                self.command_process.terminate()
        except:
            pass
    
    def execute_command(self):
        """Execute the script generated by this object and store the process"""
        
        xmlpath = self.command_xmlpath
        
        if DEBUG_PRINT:
            print("ExporterCommand.execute_command()")
            print("xmlpath: " + xmlpath)

        # Perform delayed building and close archive before executing
        if self._pointer_file:
            if self.delay_build:
                self.build_code("begin")
                self.build_code("middle")
                self.build_code("end")
            
            self.close_archive()
        
        # Resolve execute attribute to determine execution and trigger EXEC links
        try:
            execute = eval(rm.pipeline_manager.get_attr(self, xmlpath, "execute",
                                                           True, "True"))
        except:
            raise rm_error.RibmosaicError("Invalid result for \"execute\" attribute in " + \
                                          xmlpath + ", expected True/False")
        
        if execute:
            try:
                self.close_archive()
                
                # Run command as sub process and save pointer
                command = self.archive_path + self.archive_name
                
                try: # Try it unix style
                    self.command_process = subprocess.Popen(command, shell=True,
                                                            preexec_fn=os.setsid)
                except: # Try it windows style
                    self.command_process = subprocess.Popen(command, shell=True)
            except:
                raise rm_error.RibmosaicError("Could not execute command " + command)
            
            # Only poll and apply target regexes if not interactive
            if not self.pointer_datablock.ribmosaic_interactive:
                # Wait for process to quit while checking for key presses
                while self.command_process.poll() is None:
                    try:
                        self._test_break()
                    except:
                        self.terminate_command()
                
                # Apply any target regexes
                self.apply_regextargets()
    
    def build_code(self, element, close=False):
        """Build and write element panel code to archive.
        This is just a wrapper for ExporterArchive.write_code().
        
        element = The panels code element to build
        close = If true closes archive when complete
        """

        if DEBUG_PRINT:
            print("ExporterCommand.build_code()")
        
        self.write_code(self.command_xmlpath + "/" + element, close)


class ExporterUtility(ExporterArchive):
    """This subclass represents utility RIB created from the data in a xmlpath
    of a pipeline utility panel. It provides all necessary public methods and
    attributes for building utility RIB from XML source.
    """
    
    
    # #### Public attributes
    
    utility_xmlpath = "" # XML path to utility panel this object represents
    
    
    # #### Private methods
    
    def __init__(self, export_object=None, utility_xmlpath=""):
        """Initialize attributes using export_object and utility_xmlpath.
        
        export_object = The archive object this panel writes to
        utility_xmlpath = XML pipeline path to utility panel to process
        """
        
        self.utility_xmlpath = utility_xmlpath
        
        ExporterArchive.__init__(self, export_object)
        
        # Automatically add regexes to parent archive
        if utility_xmlpath:
            self.add_regexes(utility_xmlpath + "/regexes")
    
    def build_code(self, element, close=False):
        """Build and write element panel code to archive.
        This is just a wrapper for ExporterArchive.write_code().
        
        element = The panels code element to build
        close = If true closes archive when complete
        """

        if DEBUG_PRINT:
            print("ExporterUtility.build_code()")
        
        self.write_code(self.utility_xmlpath + "/" + element, close)


class ExporterShader(ExporterArchive):
    """This subclass represents shader RIB created from the data in a xmlpath
    of a pipeline shader panel. It provides all necessary public methods and
    attributes for building shader RIB from XML source.
    """
    
    
    # #### Public attributes
    
    shader_xmlpath = "" # XML path to shader panel this object represents
    
    
    # #### Private methods
    
    def __init__(self, export_object=None, shader_xmlpath=""):
        """Initialize attributes using export_object and utility_xmlpath.
        
        export_object = The archive object this panel writes to
        shader_xmlpath = XML pipeline path to utility panel to process
        """
        
        self.shader_xmlpath = shader_xmlpath
        
        ExporterArchive.__init__(self, export_object)
        
        # Automatically add regexes to parent archive
        if shader_xmlpath:
            self.add_regexes(shader_xmlpath + "/regexes")
    
    def build_code(self, element, close=False):
        """Build and write element panel code to archive.
        This is just a wrapper for ExporterArchive.write_code().
        
        element = The panels code element to build
        close = If true closes archive when complete
        """
        
        if DEBUG_PRINT:
            print("ExporterShader.build_code()")

        self.write_code(self.shader_xmlpath + "/" + element, close)


# #### Exporter object sub classes (all derived from ExporterArchive)

class ExportPass(ExporterArchive):
    """This subclass represents a pass archive created from the data in its
    export context attributes (setup before initialization by pipeline_manager's
    export_rib()). It provides all necessary public methods and attributes for
    creating a root pass RIB archive.
    """
    
    
    # #### Private methods
    
    def __init__(self, export_object=None, archive_path="", archive_name=""):
        """Initialize attributes using export_object and parameters.
        Automatically create the RIB this object represents.
        
        export_object = Any object subclassed from ExportContext
        archive_path = Path to save archive to (from export_object otherwise)
        archive_name = Name to save archive as (from export_object otherwise)
        """
        
        ExporterArchive.__init__(self, export_object, archive_path, archive_name)
        
        # Determine if compressed RIB is enabled
        if self.pointer_datablock:
            compress = self.pointer_datablock.ribmosaic_compressrib
        else:
            compress = False
        
        self.open_archive(gzipped=compress)
    
    def _export_lights(self, lights):
        if DEBUG_PRINT:
            print("ExportPass._export_lights()")

        for idx, light in enumerate(lights):
           target_name = light.name + ".rib"
           self.current_lightid = idx
           try:
               el = ExportLight(self, light)
               el.export_rib()
               del el
           except:
               el.close_archive()
               del el
               raise rm_error.RibmosaicError("Failed to build light RIB " + \
                                             target_name, sys.exc_info())
         
    def _export_objects(self, objects):
        if DEBUG_PRINT:
            print("ExportPass._export_lights()")

        for ob in objects:
            target_name = ob.name + ".rib"
            try:
                eo = ExportObject(self, ob)
                eo.export_rib()
                del eo
            except:
                eo.close_archive()
                del eo
                raise rm_error.RibmosaicError("Failed to build object RIB " + \
                                              target_name, sys.exc_info())
 
    
    # #### Public methods
    
    def export_rib(self):
        """ """
        
        # TODO Setup RIB header from scene properties
        # TODO Setup insertion point for instance geometry
        # TODO Setup sub-frames and camera's
        # TODO Setup world shaders
        # TODO Setup insertion point for light archive
        
        #world = ExportWorld(self)
        #world.export_rib()
        #del world
        
        #objects = ExportObject(self)
        #objects.export_rib()
        #del objects
        
        if DEBUG_PRINT:
            print("ExportPass.export_rib()")
        
        
        # #### Setup basic test RIB for now
        
        # Push objects attributes
        pipeline = self.context_pipeline
        category = self.context_category
        panel = self.context_panel
        datablock = self.pointer_datablock
        
        # Panel object lists
        scene_utilities = []
        render_utilities = []
        world_utilities = []
        world_shaders = []
        
        # Initialize objects for enabled panels in render and scene
        for p in rm.pipeline_manager.list_panels("utility_panels", window='SCENE'):
            segs = p.split("/")
            self.context_pipeline = segs[0]
            self.context_category = segs[1]
            self.context_panel = segs[2]
            
            if self._panel_enabled():
                scene_utilities.append(ExporterUtility(self, p))
        
        for p in rm.pipeline_manager.list_panels("utility_panels", window='RENDER'):
            segs = p.split("/")
            self.context_pipeline = segs[0]
            self.context_category = segs[1]
            self.context_panel = segs[2]
            
            if self._panel_enabled():
                render_utilities.append(ExporterUtility(self, p))
        
        # Initialize objects for enabled panels in world
        self.pointer_datablock = datablock.world
        
        for p in rm.pipeline_manager.list_panels("utility_panels", window='WORLD'):
            segs = p.split("/")
            self.context_pipeline = segs[0]
            self.context_category = segs[1]
            self.context_panel = segs[2]
            
            if self._panel_enabled():
                world_utilities.append(ExporterUtility(self, p))
        
        for p in rm.pipeline_manager.list_panels("shader_panels", window='WORLD'):
            segs = p.split("/")
            self.context_pipeline = segs[0]
            self.context_category = segs[1]
            self.context_panel = segs[2]
            
            if self._panel_enabled():
                world_shaders.append(ExporterShader(self, p))
        
        # Pop objects attributes
        self.context_pipeline = pipeline
        self.context_category = category
        self.context_panel = panel
        self.pointer_datablock = datablock
        
        # Write everything to archive
        for p in scene_utilities:
            p.build_code("begin")
        
        self.riFrameBegin()
        
        for p in render_utilities:
            p.build_code("begin")
        
        self.write_text(self._resolve_links(
        "Format @[EVAL:.dims_resx:]@ @[EVAL:.dims_resy:]@ 1\n"
        "@[EVAL:\"PixelSamples @[EVAL:.pointer_pass.pass_samples_x:]@ "
        "@[EVAL:.pointer_pass.pass_samples_y:]@\" if "
        "@[EVAL:.pointer_pass.pass_samples_x:]@ else \"\" :]@\n"
        "@[EVAL:\"ShadingRate @[EVAL:.pointer_pass.pass_shadingrate:]@\" "
        "if @[EVAL:.pointer_pass.pass_shadingrate:]@ else \"\":]@\n"))

        # export camera - for now default to the camera in the scene
        # TODO the pass camera overrides the scene's camera
        # make use of ExportObject to do the dirty work 
        #"Translate 0 0 1\n"
        try:
           cam = ExportObject(self, self.get_scene().camera)
           cam.export_rib()
           del cam
        except:
           cam.close_archive()
           del cam
           raise rm_error.RibmosaicError("Failed to build camera " + \
                                         sys.exc_info())

           

        self.write_text("Sides 2\n")
        self.riWorldBegin()
        self.write_text("Attribute \"displacementbound\" \"float sphere\" [ 0.05 ] "
        "\"string coordinatesystem\" [ \"shader\" ]\n")
        
        for p in world_utilities:
            p.build_code("begin")
        
        for p in world_shaders:
            p.build_code("rib")
        
        # figure out what objects in the scene are renderable
        # build a collection of all renderable objects which includes:
        # light, camera, mesh, empty
        objects, lights, cameras = get_renderables(self.get_scene())

        # first export lights to rib
        self._export_lights(lights)

        # export all the objects to RIB
        self._export_objects(objects)
       
        for p in world_utilities:
            p.build_code("end")
        
        self.riWorldEnd()
        
        for p in render_utilities:
            p.build_code("end")
        
        self.riFrameEnd()
        
        for p in scene_utilities:
            p.build_code("end")
        
        self.close_archive()

    def get_scene(self):
        return self.pointer_datablock


class ExportWorld(ExporterArchive):
    """Represents shaders on world data-blocks"""
    
    
    # #### Public methods
    
    def export(self):
        """ """
        
        print("Exporting world...")


class ExportObject(ExporterArchive):
    """This subclass represents object transforms and uses its inherited
    attributes to setup and export a object. The object"s objdata and particles
    are then iterated through according to material associations. If the object
    contains children, duplis or particles objects they are iterated through
    and each is passed to a new instance of ExportObjects. This class also
    automatically handles nesting of CSG through parenting.
    """
    
    # #### Private methods
    
    def __init__(self, export_object=None, pointer_object=None):
        """Initialize attributes using export_object and parameters.
        Automatically create the RIB this object represents.
        
        export_object = ExportObject subclassed from ExportContext
       """
        
        ExporterArchive.__init__(self, export_object)
        self._set_pointer_datablock(pointer_object)
        
        # TODO open the archive if using ReadArchive mode
        # for now default to using the parents file pointer

        # Determine if compressed RIB is enabled in the parent
        #if export_object:
        #    compress = getattr(export_object, "is_gzip", False)
        #else:
        #    compress = False
        
        #self.open_archive(gzipped=compress)

    def _export_camera_rib(self):
        if DEBUG_PRINT:
            print('ExportObject._export_camera()')

        ob = self.get_object()
        scene = self.get_scene()
        r = scene.render
        camera = ob.data
    
        xaspect, yaspect, aspectratio = render_get_aspect(r)
    
        # TODO get depth of field option from ribmosaic user panel
        #if rm.depth_of_field:
        #    if camera.dof_object:
        #        dof_distance = (ob.location - camera.dof_object.location).length
        #    else:
        #        dof_distance = camera.dof_distance
        #    file.write('DepthOfField %f 1.0 %f\n' % (rm.fstop, dof_distance))
        #if scene.renderman.motion_blur:
        #    file.write('Shutter %f %f\n' % (rm.shutter_open, rm.shutter_close))
        #    file.write('Option "shutter" "efficiency" [ %f %f ] \n' % 
        #        (rm.shutter_efficiency_open, rm.shutter_efficiency_close))

        self.write_text('Clipping %f %f\n' % (camera.clip_start, camera.clip_end))
    
        if camera.type == 'PERSP':
            lens= camera.lens
            fov= 360.0*math.atan(16.0/lens/aspectratio)/math.pi
            self.write_text('Projection "perspective" "fov" %f\n' % fov)
        else:
            lens= camera.ortho_scale
            xaspect= xaspect*lens/(aspectratio*2.0)
            yaspect= yaspect*lens/(aspectratio*2.0)
            self.write('Projection "orthographic"\n')

        self.write_text('ScreenWindow %f %f %f %f\n' % (-xaspect, xaspect, -yaspect, yaspect))


        # build a transform matrix that is looking at the scene
        mat = ob.matrix_world
        loc = mat.to_translation()
        rot = mat.to_euler()

        # setup the look vector which defaults to looking down the Z axis
        s = mathutils.Matrix(([1,0,0,0],[0,1,0,0],[0,0,-1,0],[0,0,0,1]))
        r = mathutils.Matrix.Rotation(-rot[0], 4, 'X')
        r *= mathutils.Matrix.Rotation(-rot[1], 4, 'Y')
        r *= mathutils.Matrix.Rotation(-rot[2], 4, 'Z')
        l = mathutils.Matrix.Translation(-loc)
    
        m = s * r * l
        
        self.write_text('Transform %s\n' % rib_mat_str(m))

    
    # #### Public methods
    
    def export(self):
        """ """
        
        print("Exporting objects...")
        
        light = ExportLight(self)
        light.export_rib()
        del light
        
        material = ExportMaterial(self)
        material.export_rib()
        del material
        
        objdata = ExportObjdata(self)
        objdata.export_rib()
        del objdata
        
        particles = ExportParticles(self)
        particles.export_rib()
        del particles

    def export_rib(self):
        """ """

        print("ExportObject.export_rib()")

        ob = self.get_object()

        if ob.type == 'CAMERA':
            self._export_camera_rib()
        else:
            if ob.parent:
                mat = ob.parent.matrix_world * ob.matrix_local
            else:
                mat = ob.matrix_world
            print(mat)
            # if a camera object then do special camera output
            #     FIXME this is just test code
            #self.write_text('##Renderman  \n')
            self.riAttributeBegin()
            self.write_text('Attribute "identifier" "name" [ "%s" ]\n' % self.data_name)
            self.write_text('Transform %s\n' % rib_mat_str(mat))
            # export object data
            # let the ExportObjdata instance decide how to export the object data
            try:
                eod = ExportObjdata(self)
                eod.export_rib()
                del eod
            except:
                eod.close_archive()
                raise rm_error.RibmosaicError("Failed to build object data RIB " + \
                                             self.data_name, sys.exc_info())
          
            # create ExportObjectData

            self.riAttributeEnd()
            self.write_text('\n')
            self.close_archive();

    def get_scene(self):
        return self.pointer_parent.get_scene()

    def get_object(self):
        return self.pointer_datablock


class ExportLight(ExporterArchive):
    """Represents shaders on lamp data-blocks"""
        
    def __init__(self, export_object=None, pointer_object=None):
        """Initialize attributes using export_object and parameters.
        Automatically create the RIB this object represents.
        
        export_object = ExportObject subclassed from ExportContext
       """
        
        ExporterArchive.__init__(self, export_object)
        self._set_pointer_datablock(pointer_object)
     
    # #### Public methods
    
    def export(self):
        """ """
        
        print("Exporting lamp...")

    def export_rib(self):
        if DEBUG_PRINT:
            print("ExportLight.export_rib()")
            
        ob = self.pointer_datablock
        lamp = ob.data

        if ob.parent:
            m = ob.parent.matrix_world * ob.matrix_local
        else:
            m = ob.matrix_world
            loc = m.to_translation()
    
        loc = m.to_translation()
        lvec = [loc[0]-m[2][0], loc[1]-m[2][1], loc[2]-m[2][2]]
        params = []
    
        self.riAttributeBegin()
        # TODO default to a pointlight for now
        self.write_text("LightSource \"pointlight\" %s \"uniform point from\" "
                        "[ %s ]\n" % (self.current_lightid, rib_param_val('float', loc)))
        
        self.riAttributeEnd()
        self.riIlluminate(self.current_lightid);
        self.write_text('\n')
        


class ExportMaterial(ExporterArchive):
    """Represents shaders on materials related to material data-blocks"""
    
    
    # #### Public methods
    
    def export(self):
        """ """
        
        print("Exporting materials...")


class ExportObjdata(ExporterArchive):
    """Represents geometry, lights and cameras using objectdata data-blocks.
    Can also handle export of multiple meshes setup in LOD list
    """
    
    def __init__(self, export_object=None):
        """Initialize attributes using export_object and parameters.
        Automatically create the RIB this object data represents.
        
        export_object = Any object subclassed from ExportContext
       """
        
        ExporterArchive.__init__(self, export_object)
        
        # Determine if compressed RIB is enabled
        #if self.pointer_datablock:
        #    compress = self.pointer_datablock.ribmosaic_compressrib
        #else:
        #    compress = False
        
        #self.open_archive(gzipped=compress)


    def _export_polygon_mesh(self):
       # create a mesh that has all modifiers applied to mesh data
        mesh = create_mesh(self.get_scene(), self.get_object())
        # set the file pointer for ribify
        rm.ribify.pointer_file = self._pointer_file
        # ribify the mesh data
        rm.ribify.mesh_pointspolygons(mesh)

        # don't need the mesh data anymore so tell blender to
        # get rid of it
        bpy.data.meshes.remove(mesh)

    def _export_geometry(self):
        if DEBUG_PRINT:
            print("ExportObjdata._export_geometry")

        # determine whate type of geometry is to be exported
        prim = detect_primitive(self.get_object())

        if prim == 'POLYGON_MESH':
          self._export_polygon_mesh()
   
    # #### Public methods
    
    # TODO just a test method
    def export(self):
        """ """
        
        if DEBUG_PRINT:
             print("Exporting object data...")

        rm.ribify.mesh_pointspolygons(None)
        rm.ribify.mesh_subdivisionmesh(None)
        rm.ribify.mesh_points(None)
        rm.ribify.mesh_curves(None)
        rm.ribify.curve_cyclic_poly(None)
        rm.ribify.curve_cyclic_bezier(None)
        rm.ribify.curve_cyclic_nurbs(None)
        rm.ribify.curve_noncyclic_poly(None)
        rm.ribify.curve_noncyclic_bezier(None)
        rm.ribify.curve_noncyclic_nurbs(None)
        rm.ribify.curve_points(None)
        rm.ribify.surface_nupatch(None)
        rm.ribify.surface_points(None)
        rm.ribify.metaball_blobby(None)
        rm.ribify.metaball_points(None)
        rm.ribify.data_to_primvar(None, member="N", define="N",
                                     ptype="normal", pclass="varying")

    # export the blender object data into RIB format
    def export_rib(self):
        if DEBUG_PRINT:
            print('ExportObjData.export_rib()')

        # determine what type of object data needs to be exported
        if self.pointer_datablock.type in ('MESH', 'EMPTY'):
           self. _export_geometry()

    # helper method to get the blender scene the object is in
    def get_scene(self):
        return self.pointer_parent.get_scene()

    # helper method to get the blender object that is currently being exported
    def get_object(self):
        return self.pointer_datablock
 
class ExportParticles(ExporterArchive):
    """Represents particle systems connected to particle data-blocks"""
    
    
    # #### Public methods
    
    def export(self):
        """ """
        
        print("Exporting particles...")
        rm.ribify.particles_points(None)
        rm.ribify.particles_curves(None)
        rm.ribify.data_to_primvar(None, member="N", define="N",
                                     ptype="normal", pclass="varying")


