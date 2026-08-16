extends Control

const MENU_ITEMS := [
	["PLAY", "Browse inserted USB, SD, CD, DVD, and internal games"],
	["LIBRARY", "All detected games and media"],
	["SAVES", "Back up, restore, copy, and delete profile saves"],
	["CHEATS", "Manage disabled-by-default cheats per game"],
	["CONTROLLERS", "Xbox-style defaults and per-game layouts"],
	["SETTINGS", "Display, audio, network, artwork, and storage"],
	["POWER", "Soft reboot, restart, or shut down"],
]

var boot_time := 0.0
var boot_finished := false
var selected_index := 0
var menu_buttons: Array[Button] = []
var boot_layer: Control
var boot_logo: Label
var menu_root: Control
var detail_label: Label
var status_label: Label
var profile_label: Label
var ssh_label: Label
var pulse := 0.0
var library_overlay: PanelContainer
var library_poll := 0.0
var detected_media_count := 0

func _ready() -> void:
	set_process(true)
	set_process_input(true)
	_build_menu()
	_build_boot_layer()
	_refresh_media_state()
	get_viewport().size_changed.connect(queue_redraw)
	queue_redraw()

func _build_menu() -> void:
	menu_root = Control.new()
	menu_root.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	add_child(menu_root)

	var title := Label.new()
	title.text = "PULSEARC"
	title.position = Vector2(54, 35)
	title.add_theme_font_size_override("font_size", 48)
	title.add_theme_color_override("font_color", Color("50e8ff"))
	menu_root.add_child(title)

	var subtitle := Label.new()
	subtitle.text = "DIRECT MEDIA GAMING SYSTEM  •  DEVELOPMENT MILESTONE 1"
	subtitle.position = Vector2(58, 92)
	subtitle.add_theme_font_size_override("font_size", 15)
	subtitle.add_theme_color_override("font_color", Color("c88bff"))
	menu_root.add_child(subtitle)

	profile_label = Label.new()
	profile_label.text = "●  DEFAULT PROFILE"
	profile_label.horizontal_alignment = HORIZONTAL_ALIGNMENT_RIGHT
	profile_label.position = Vector2(930, 48)
	profile_label.size = Vector2(290, 40)
	profile_label.add_theme_font_size_override("font_size", 18)
	profile_label.add_theme_color_override("font_color", Color("ff55c8"))
	menu_root.add_child(profile_label)

	var menu := VBoxContainer.new()
	menu.position = Vector2(65, 160)
	menu.size = Vector2(430, 470)
	menu.add_theme_constant_override("separation", 8)
	menu_root.add_child(menu)

	for index in MENU_ITEMS.size():
		var button := Button.new()
		button.text = MENU_ITEMS[index][0]
		button.custom_minimum_size = Vector2(410, 54)
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.add_theme_font_size_override("font_size", 23)
		button.add_theme_color_override("font_color", Color("b4c6ff"))
		button.add_theme_color_override("font_focus_color", Color("ffffff"))
		button.focus_mode = Control.FOCUS_ALL
		button.mouse_entered.connect(func() -> void: button.grab_focus())
		button.focus_entered.connect(_on_focus.bind(index))
		button.pressed.connect(_on_pressed.bind(index))
		menu.add_child(button)
		menu_buttons.append(button)

	var detail_panel := PanelContainer.new()
	detail_panel.position = Vector2(570, 175)
	detail_panel.size = Vector2(640, 370)
	menu_root.add_child(detail_panel)
	var detail_box := VBoxContainer.new()
	detail_box.add_theme_constant_override("separation", 18)
	detail_panel.add_child(detail_box)
	var heading := Label.new()
	heading.text = "READY"
	heading.add_theme_font_size_override("font_size", 34)
	heading.add_theme_color_override("font_color", Color("ff65ce"))
	detail_box.add_child(heading)
	detail_label = Label.new()
	detail_label.text = MENU_ITEMS[0][1]
	detail_label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	detail_label.add_theme_font_size_override("font_size", 22)
	detail_label.add_theme_color_override("font_color", Color("dce8ff"))
	detail_box.add_child(detail_label)
	var runtime_label := Label.new()
	runtime_label.text = "INTERNAL RUNTIMES\nOpenGL compatibility • Vulkan • DXVK • VKD3D-Proton\nFAT32 • exFAT • NTFS • Linux filesystems • optical media"
	runtime_label.add_theme_font_size_override("font_size", 17)
	runtime_label.add_theme_color_override("font_color", Color("7cdfff"))
	detail_box.add_child(runtime_label)

	status_label = Label.new()
	status_label.text = "A SELECT   •   B BACK   •   VIEW + MENU EXIT GAME"
	status_label.position = Vector2(570, 580)
	status_label.size = Vector2(640, 40)
	status_label.add_theme_font_size_override("font_size", 17)
	status_label.add_theme_color_override("font_color", Color("a9b5dc"))
	menu_root.add_child(status_label)
	ssh_label = Label.new()
	ssh_label.text = _ssh_status()
	ssh_label.position = Vector2(54, 675)
	ssh_label.size = Vector2(1170, 28)
	ssh_label.add_theme_font_size_override("font_size", 14)
	ssh_label.add_theme_color_override("font_color", Color("67d9b5"))
	menu_root.add_child(ssh_label)
	menu_root.modulate.a = 0.0

func _build_boot_layer() -> void:
	boot_layer = Control.new()
	boot_layer.set_anchors_and_offsets_preset(Control.PRESET_FULL_RECT)
	boot_layer.mouse_filter = Control.MOUSE_FILTER_STOP
	add_child(boot_layer)
	boot_logo = Label.new()
	boot_logo.text = "PULSEARC"
	boot_logo.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	boot_logo.vertical_alignment = VERTICAL_ALIGNMENT_CENTER
	boot_logo.set_anchors_preset(Control.PRESET_CENTER)
	boot_logo.position = Vector2(-310, -75)
	boot_logo.size = Vector2(620, 150)
	boot_logo.pivot_offset = boot_logo.size / 2.0
	boot_logo.add_theme_font_size_override("font_size", 70)
	boot_logo.add_theme_color_override("font_color", Color("65efff"))
	boot_layer.add_child(boot_logo)
	var boot_subtitle := Label.new()
	boot_subtitle.text = "MEDIA  •  MEMORY  •  MOMENTUM"
	boot_subtitle.horizontal_alignment = HORIZONTAL_ALIGNMENT_CENTER
	boot_subtitle.set_anchors_preset(Control.PRESET_CENTER)
	boot_subtitle.position = Vector2(-300, 80)
	boot_subtitle.size = Vector2(600, 40)
	boot_subtitle.add_theme_font_size_override("font_size", 17)
	boot_subtitle.add_theme_color_override("font_color", Color("ff5ecb"))
	boot_layer.add_child(boot_subtitle)

func _process(delta: float) -> void:
	pulse += delta
	library_poll += delta
	if library_poll >= 1.0:
		library_poll = 0.0
		_refresh_media_state()
	queue_redraw()
	if not boot_finished:
		boot_time += delta
		var entrance: float = clampf(boot_time / 1.0, 0.0, 1.0)
		boot_logo.scale = Vector2.ONE * lerp(0.55, 1.0, ease(entrance, -2.0))
		boot_logo.modulate.a = entrance
		if boot_time > 2.6:
			var fade: float = clampf((boot_time - 2.6) / 0.65, 0.0, 1.0)
			boot_layer.modulate.a = 1.0 - fade
			menu_root.modulate.a = fade
		if boot_time >= 3.3:
			boot_finished = true
			boot_layer.queue_free()
			menu_root.modulate.a = 1.0
			_focus_first_available()

func _focus_first_available() -> void:
	if menu_buttons[0].disabled:
		menu_buttons[1].grab_focus()
	else:
		menu_buttons[0].grab_focus()

func _refresh_media_state() -> void:
	var count := _read_library().size()
	if count == detected_media_count and menu_buttons[0].disabled == (count == 0):
		return
	detected_media_count = count
	menu_buttons[0].disabled = count == 0
	menu_buttons[0].tooltip_text = "Insert game media to enable PLAY" if count == 0 else "%d detected title(s)" % count
	if count == 0 and selected_index == 0 and boot_finished:
		menu_buttons[1].grab_focus()

func _draw() -> void:
	var view := size
	draw_rect(Rect2(Vector2.ZERO, view), Color("02030f"))
	for i in range(42):
		var seed := float((i * 73) % 997) / 997.0
		var x := seed * view.x
		var y := float((i * 137) % 541) / 541.0 * view.y * 0.62
		var glow := 0.35 + 0.35 * sin(pulse * 0.7 + i)
		draw_circle(Vector2(x, y), 1.2, Color(0.35, 0.75, 1.0, glow))
	var horizon := view.y * 0.67
	draw_line(Vector2(0, horizon), Vector2(view.x, horizon), Color("fa49c6"), 2.0)
	for i in range(1, 18):
		var t := float(i) / 18.0
		var y := horizon + pow(t, 2.2) * (view.y - horizon)
		draw_line(Vector2(0, y), Vector2(view.x, y), Color(0.2, 0.65, 1.0, 0.38), 1.0)
	for i in range(-14, 15):
		var bottom_x := view.x * 0.5 + i * view.x / 12.0
		draw_line(Vector2(view.x * 0.5, horizon), Vector2(bottom_x, view.y), Color(0.9, 0.2, 0.85, 0.32), 1.0)
	var sun_center := Vector2(view.x * 0.78, horizon - 40)
	for radius in range(105, 5, -7):
		var alpha := 0.012 + float(105 - radius) / 105.0 * 0.008
		draw_circle(sun_center, radius, Color(1.0, 0.25, 0.58, alpha))

func _on_focus(index: int) -> void:
	selected_index = index
	detail_label.text = MENU_ITEMS[index][1]

func _on_pressed(index: int) -> void:
	if index == 0 and detected_media_count == 0:
		status_label.text = "INSERT USB, SD, CD, DVD, OR A LEGACY KZI CARTRIDGE"
		return
	if index == 0 or index == 1:
		_show_library()
		return
	if index >= 2 and index <= 4:
		_show_manager(index)
		return
	if index == 5:
		_show_settings()
		return
	if index == 6:
		_show_power()
		return

func _show_manager(index: int) -> void:
	if is_instance_valid(library_overlay):
		return
	library_overlay = PanelContainer.new()
	library_overlay.position = Vector2(80, 125)
	library_overlay.size = Vector2(size.x - 160, size.y - 180)
	add_child(library_overlay)
	var outer := VBoxContainer.new()
	outer.add_theme_constant_override("separation", 10)
	library_overlay.add_child(outer)
	var heading := Label.new()
	heading.text = MENU_ITEMS[index][0]
	heading.add_theme_font_size_override("font_size", 30)
	heading.add_theme_color_override("font_color", Color("ff5dcc"))
	outer.add_child(heading)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	outer.add_child(scroll)
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 6)
	scroll.add_child(list)
	if index == 4:
		_add_manager_line(list, "XBOX-STYLE UNIVERSAL DEFAULT")
		_add_manager_line(list, "A South  •  B East  •  X West  •  Y North")
		_add_manager_line(list, "View + Menu: Exit game")
		_add_manager_line(list, "View + A: Emulator menu")
		_add_manager_line(list, "Per-system and per-game overrides are stored in the active profile.")
	else:
		var manager := "saves" if index == 2 else "cheats"
		var values: Array = _manager_data(manager)
		if values.is_empty():
			_add_manager_line(list, "No %s have been created for this profile yet." % manager)
		for value in values:
			if not value is Dictionary:
				continue
			var entry: Dictionary = value
			if manager == "saves":
				var size_bytes := int(entry.get("size", 0))
				_add_manager_line(list, "%s   •   %.2f MB" % [str(entry.get("content_id", "unknown")), size_bytes / 1048576.0])
			else:
				_add_manager_line(list, "%s   [%s]   •   %s cheats / %s enabled" % [
					str(entry.get("title", "Unknown")), str(entry.get("platform", "unknown")).to_upper(),
					str(entry.get("cheat_count", 0)), str(entry.get("enabled_count", 0))])
	var close := Button.new()
	close.text = "B  BACK"
	close.custom_minimum_size = Vector2(0, 46)
	close.pressed.connect(_close_library)
	outer.add_child(close)
	close.grab_focus()

func _add_manager_line(parent: VBoxContainer, text: String) -> void:
	var label := Label.new()
	label.text = text
	label.autowrap_mode = TextServer.AUTOWRAP_WORD_SMART
	label.custom_minimum_size = Vector2(0, 34)
	label.add_theme_font_size_override("font_size", 19)
	label.add_theme_color_override("font_color", Color("d5e2ff"))
	parent.add_child(label)

func _new_overlay(title: String) -> VBoxContainer:
	library_overlay = PanelContainer.new()
	library_overlay.position = Vector2(170, 125)
	library_overlay.size = Vector2(size.x - 340, size.y - 210)
	add_child(library_overlay)
	var outer := VBoxContainer.new()
	outer.add_theme_constant_override("separation", 12)
	library_overlay.add_child(outer)
	var heading := Label.new()
	heading.text = title
	heading.add_theme_font_size_override("font_size", 30)
	heading.add_theme_color_override("font_color", Color("ff5dcc"))
	outer.add_child(heading)
	return outer

func _show_settings() -> void:
	if is_instance_valid(library_overlay):
		return
	var outer := _new_overlay("SETTINGS")
	_add_manager_line(outer, "DISPLAY POLICY")
	var graphics := _read_json_file("/run/pulsearc/graphics.json")
	if graphics.is_empty():
		_add_manager_line(outer, "Safe Xorg + OpenGL compatibility mode (hardware probe pending)")
	else:
		_add_manager_line(outer, "%s  •  %s  •  %s" % [
			str(graphics.get("session_backend", "x11")).to_upper(),
			str(graphics.get("windows_renderer", "wined3d")).to_upper(),
			str(graphics.get("gamescope", "unsupported")).to_upper(),
		])
	_add_manager_line(outer, "REMOVABLE MEDIA")
	_add_manager_line(outer, "FAT32 • exFAT • NTFS • ext4 • Btrfs • XFS • F2FS • ISO9660 • UDF")
	_add_manager_line(outer, "SSH/SFTP")
	_add_manager_line(outer, _ssh_status())
	var close := Button.new()
	close.text = "B  BACK"
	close.custom_minimum_size = Vector2(0, 48)
	close.pressed.connect(_close_library)
	outer.add_child(close)
	close.grab_focus()

func _show_power() -> void:
	if is_instance_valid(library_overlay):
		return
	var outer := _new_overlay("POWER")
	var choices := [
		["SOFT RESTART FRONTEND", "soft"],
		["RESTART COMPUTER", "reboot"],
		["SHUT DOWN", "poweroff"],
	]
	for choice in choices:
		var button := Button.new()
		button.text = choice[0]
		button.alignment = HORIZONTAL_ALIGNMENT_LEFT
		button.custom_minimum_size = Vector2(0, 56)
		button.add_theme_font_size_override("font_size", 21)
		button.pressed.connect(_power_action.bind(choice[1]))
		outer.add_child(button)
	var cancel := Button.new()
	cancel.text = "B  CANCEL"
	cancel.custom_minimum_size = Vector2(0, 48)
	cancel.pressed.connect(_close_library)
	outer.add_child(cancel)
	(outer.get_child(1) as Button).grab_focus()

func _power_action(action: String) -> void:
	if action == "soft":
		get_tree().quit(75)
		return
	OS.create_process("/usr/bin/sudo", PackedStringArray(["/usr/bin/systemctl", action]))

func _read_json_file(path: String) -> Dictionary:
	if not FileAccess.file_exists(path):
		return {}
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return {}
	var value: Variant = JSON.parse_string(file.get_as_text())
	return value if value is Dictionary else {}

func _manager_data(manager: String) -> Array:
	if not FileAccess.file_exists("/usr/lib/pulsearc/core/pulsearc/control.py"):
		return []
	var output: Array = []
	var arguments := PackedStringArray(["-m", "pulsearc.control", "manager-json", manager, "--profile", "default"])
	var result := OS.execute("/usr/bin/python", arguments, output, true)
	if result != 0 or output.is_empty():
		return []
	var parsed: Variant = JSON.parse_string(str(output[0]))
	return parsed if parsed is Array else []

func _ssh_status() -> String:
	if not FileAccess.file_exists("/etc/pulsearc/channel"):
		return "SSH/SFTP is enabled in hardware development images"
	var channel_file := FileAccess.open("/etc/pulsearc/channel", FileAccess.READ)
	if channel_file == null or channel_file.get_as_text().strip_edges() != "development":
		return "SSH/SFTP • Open Settings to pair a key"
	var address := "pending network"
	var output: Array = []
	if OS.execute("/usr/bin/hostname", PackedStringArray(["-I"]), output, false) == 0 and not output.is_empty():
		address = str(output[0]).strip_edges().split(" ")[0]
	var credential_path := "/var/lib/pulsearc/firstboot-ssh.txt"
	if not FileAccess.file_exists(credential_path):
		return "SSH gamer@%s • generating first-boot password" % address
	var credential := FileAccess.open(credential_path, FileAccess.READ)
	var password := "see TTY"
	if credential != null:
		for line in credential.get_as_text().split("\n"):
			if line.begins_with("Password: "):
				password = line.trim_prefix("Password: ")
	return "DEVELOPMENT SSH  •  gamer@%s  •  password %s" % [address, password]

func _show_library() -> void:
	if is_instance_valid(library_overlay):
		return
	library_overlay = PanelContainer.new()
	library_overlay.position = Vector2(42, 120)
	library_overlay.size = Vector2(size.x - 84, size.y - 160)
	add_child(library_overlay)
	var outer := VBoxContainer.new()
	outer.add_theme_constant_override("separation", 12)
	library_overlay.add_child(outer)
	var heading := Label.new()
	heading.text = "DETECTED MEDIA"
	heading.add_theme_font_size_override("font_size", 30)
	heading.add_theme_color_override("font_color", Color("53eaff"))
	outer.add_child(heading)
	var scroll := ScrollContainer.new()
	scroll.size_flags_vertical = Control.SIZE_EXPAND_FILL
	outer.add_child(scroll)
	var list := VBoxContainer.new()
	list.size_flags_horizontal = Control.SIZE_EXPAND_FILL
	list.add_theme_constant_override("separation", 6)
	scroll.add_child(list)
	var entries: Array = _read_library()
	if entries.is_empty():
		var empty := Label.new()
		empty.text = "No games or media detected. Insert USB, SD, CD, or DVD media."
		empty.add_theme_font_size_override("font_size", 21)
		list.add_child(empty)
	else:
		for value in entries:
			if not value is Dictionary:
				continue
			var entry: Dictionary = value
			var item := Button.new()
			item.text = "%s    [%s]" % [str(entry.get("title", "Unknown")), str(entry.get("platform", "unknown")).to_upper()]
			item.alignment = HORIZONTAL_ALIGNMENT_LEFT
			item.custom_minimum_size = Vector2(0, 48)
			item.add_theme_font_size_override("font_size", 20)
			item.pressed.connect(_launch_entry.bind(str(entry.get("content_id", "")), str(entry.get("title", "Unknown"))))
			list.add_child(item)
	var close := Button.new()
	close.text = "B  BACK"
	close.custom_minimum_size = Vector2(0, 46)
	close.pressed.connect(_close_library)
	outer.add_child(close)
	if list.get_child_count() > 0 and list.get_child(0) is Button:
		(list.get_child(0) as Button).grab_focus()
	else:
		close.grab_focus()

func _read_library() -> Array:
	var path := "/run/pulsearc/library.json"
	if not FileAccess.file_exists(path) and OS.has_feature("editor"):
		# Editor-only sample data. Production builds never advertise fake media.
		path = "res://sample-library.json"
	if not FileAccess.file_exists(path):
		return []
	var file := FileAccess.open(path, FileAccess.READ)
	if file == null:
		return []
	var value: Variant = JSON.parse_string(file.get_as_text())
	return value if value is Array else []

func _launch_entry(content_id: String, title: String) -> void:
	if content_id.is_empty():
		return
	status_label.text = "LAUNCHING  %s" % title.to_upper()
	var args := PackedStringArray(["-m", "pulsearc.control", "launch", content_id, "--profile", "default"])
	var process_id := OS.create_process("/usr/bin/python", args)
	if process_id <= 0:
		status_label.text = "Launch service is unavailable in this development preview"
	_close_library()

func _close_library() -> void:
	if is_instance_valid(library_overlay):
		library_overlay.queue_free()
	menu_buttons[selected_index].grab_focus()

func _input(event: InputEvent) -> void:
	if not boot_finished:
		if event.is_action_pressed("ui_accept"):
			boot_time = 3.3
		get_viewport().set_input_as_handled()
		return
	if event.is_action_pressed("ui_cancel"):
		if is_instance_valid(library_overlay):
			_close_library()
		else:
			status_label.text = "BACK"
