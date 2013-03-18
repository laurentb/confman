# Only link the file if we want "desktop" files
if "desktop" in options["tags"]:
    redirect("conf2_desktop")
else:
    ignore()
