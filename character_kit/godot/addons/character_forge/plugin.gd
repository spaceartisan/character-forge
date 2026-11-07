@tool
extends EditorPlugin

var importer: EditorScenePostImportPlugin

func _enter_tree() -> void:
	importer = preload("forge_import.gd").new()
	add_scene_post_import_plugin(importer)

func _exit_tree() -> void:
	remove_scene_post_import_plugin(importer)
	importer = null
