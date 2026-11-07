@tool
extends EditorScenePostImportPlugin
## The kit's models carry baked crease shading in their vertex colours. Godot's glTF
## importer (seen in 4.7) turns "vertex colour as albedo" on for every surface except
## the first one of each mesh, so faces, coats, trousers, hats and hair come in flat.
## This switches it on for every surface.
##
## Only scenes whose .import file sets this option are touched. Character Forge's
## exports ship that .import file; other models in the project are left alone.

const OPTION := "character_forge/vertex_shading"

func _get_import_options(_path: String) -> void:
	add_import_option(OPTION, false)

func _post_process(scene: Node) -> void:
	if not get_option_value(OPTION):
		return
	for node in scene.find_children("*", "MeshInstance3D", true, false):
		var mesh: Mesh = (node as MeshInstance3D).mesh
		if mesh == null:
			continue
		for i in mesh.get_surface_count():
			var mat := mesh.surface_get_material(i) as BaseMaterial3D
			if mat:
				mat.vertex_color_use_as_albedo = true
