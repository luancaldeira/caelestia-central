-- Optional motion preset used on the development desktop. Load before central.
hl.config({ animations = { enabled = true } })
hl.curve("centralSpring", { type = "spring", mass = 1, stiffness = 238.1191, dampening = 24.21279333 })
hl.curve("centralClose", { type = "bezier", points = { {0.65, 0.05}, {0.36, 1} } })
hl.curve("centralOpen", { type = "bezier", points = { {0.34, 1.56}, {0.64, 1} } })
hl.animation({ leaf = "windows", enabled = true, speed = 4.79, spring = "centralSpring" })
hl.animation({ leaf = "windowsIn", enabled = true, speed = 3.6, bezier = "centralOpen", style = "popin 78%" })
hl.animation({ leaf = "windowsOut", enabled = true, speed = 3.6, bezier = "centralClose", style = "popin 87%" })
hl.animation({ leaf = "fadeOut", enabled = true, speed = 3.2, bezier = "centralClose" })
