#!/usr/bin/env python3
"""
Line Detection Angle Measurement Tool v2
Features:
- Rotated rectangle selection
- Robust line detection with multiple strategies
- Mouse wheel zoom and pan
- Modern UI
"""

import tkinter as tk
from tkinter import filedialog, messagebox
from PIL import Image, ImageTk, ImageDraw
import math
import os

try:
    import cv2
    import numpy as np
    CV2_AVAILABLE = True
except ImportError:
    CV2_AVAILABLE = False


class LineDetectorApp:
    def __init__(self, root):
        self.root = root
        self.root.title("📐 Line Detection Angle Tool v2")
        self.root.configure(bg="#f5f5f5")
        
        if not CV2_AVAILABLE:
            messagebox.showwarning(
                "Missing Dependency",
                "OpenCV (cv2) is required.\n\npip install opencv-python numpy"
            )
        
        # State variables
        self.image_path = None
        self.original_image = None  # Original loaded image
        self.display_image = None   # Current zoomed/panned image for display
        self.tk_image = None
        
        # Cache for performance
        self.cached_zoom_level = None
        self.cached_image = None  # Cached resized image
        
        # Zoom and pan
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.min_zoom = 0.1
        self.max_zoom = 10.0
        self.panning = False
        self.pan_start = (0, 0)
        
        # Rectangles and lines (in original image coordinates)
        self.rectangles = []
        self.detected_lines = []
        self.current_rect_points = []
        self.drawing_step = 0
        
        # Line adjustment state
        self.adjust_mode = False
        self.selected_line_idx = None
        self.selected_point_idx = None
        self.dragging = False
        self.drag_start = None
        
        # Colors
        self.colors = {
            "primary": "#2563eb",
            "secondary": "#2BC091",
            "accent": "#dc2626",
            "bg": "#f8fafc",
            "card": "#ffffff",
            "text": "#1e293b",
            "muted": "#64748b",
            "rect1": "#ef4444",
            "rect2": "#3b82f6",
            "line1": "#fbbf24",
            "line2": "#a855f7",
        }
        
        self.setup_ui()
        
    def setup_ui(self):
        main_frame = tk.Frame(self.root, bg=self.colors["bg"])
        main_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=16)
        
        self.setup_control_panel(main_frame)
        self.setup_settings_panel(main_frame)
        self.setup_canvas(main_frame)
        self.setup_status_bar(main_frame)
        
    def setup_control_panel(self, parent):
        control_frame = tk.Frame(parent, bg=self.colors["card"])
        control_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 12))
        
        inner_frame = tk.Frame(control_frame, bg=self.colors["card"])
        inner_frame.pack(fill=tk.X, padx=16, pady=12)
        
        # Buttons
        btn_frame = tk.Frame(inner_frame, bg=self.colors["card"])
        btn_frame.pack(side=tk.LEFT)
        
        self.load_btn = tk.Button(
            btn_frame, text="📁 Load Image", command=self.load_image,
            font=("Segoe UI", 10), bg=self.colors["primary"], fg="white",
            activebackground="#1d4ed8", activeforeground="white",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2"
        )
        self.load_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.detect_btn = tk.Button(
            btn_frame, text="🔍 Detect Lines", command=self.detect_all_lines,
            font=("Segoe UI", 10), bg=self.colors["secondary"], fg="white",
            activebackground="#047857", activeforeground="white",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2", state=tk.DISABLED
        )
        self.detect_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.clear_btn = tk.Button(
            btn_frame, text="🗑️ Clear All", command=self.clear_all,
            font=("Segoe UI", 10), bg=self.colors["muted"], fg="white",
            activebackground="#475569", activeforeground="white",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2"
        )
        self.clear_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.measure_btn = tk.Button(
            btn_frame, text="📏 Measure Angle", command=self.measure_angle,
            font=("Segoe UI", 10, "bold"), bg="#5cc5f6", fg="white",
            activebackground="#7c3aed", activeforeground="white",
            relief=tk.FLAT, padx=20, pady=8, cursor="hand2", state=tk.DISABLED
        )
        self.measure_btn.pack(side=tk.LEFT, padx=(0, 8))
        
        self.adjust_btn = tk.Button(
            btn_frame, text="✏️ Adjust Lines", command=self.toggle_adjust_mode,
            font=("Segoe UI", 10), bg="#dbd4ec", fg="white",
            activebackground="#c8b9e2", activeforeground="white",
            relief=tk.FLAT, padx=16, pady=8, cursor="hand2", state=tk.DISABLED
        )
        self.adjust_btn.pack(side=tk.LEFT)
        
        # Zoom controls
        zoom_frame = tk.Frame(inner_frame, bg=self.colors["card"])
        zoom_frame.pack(side=tk.LEFT, padx=(24, 0))
        
        tk.Button(
            zoom_frame, text="−", command=self.zoom_out,
            font=("Segoe UI", 12), bg=self.colors["muted"], fg="white",
            relief=tk.FLAT, width=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=2)
        
        self.zoom_label = tk.Label(
            zoom_frame, text="100%",
            font=("Segoe UI", 9), bg=self.colors["card"], fg=self.colors["text"], width=6
        )
        self.zoom_label.pack(side=tk.LEFT, padx=4)
        
        tk.Button(
            zoom_frame, text="+", command=self.zoom_in,
            font=("Segoe UI", 12), bg=self.colors["muted"], fg="white",
            relief=tk.FLAT, width=3, cursor="hand2"
        ).pack(side=tk.LEFT, padx=2)
        
        tk.Button(
            zoom_frame, text="Reset", command=self.reset_zoom,
            font=("Segoe UI", 9), bg=self.colors["muted"], fg="white",
            relief=tk.FLAT, padx=8, cursor="hand2"
        ).pack(side=tk.LEFT, padx=8)
        
        # Angle display
        angle_frame = tk.Frame(inner_frame, bg=self.colors["card"])
        angle_frame.pack(side=tk.RIGHT)
        
        # Degree display
        deg_frame = tk.Frame(angle_frame, bg=self.colors["card"])
        deg_frame.pack(side=tk.LEFT)
        
        tk.Label(
            deg_frame, text="角度:", font=("Segoe UI", 10),
            bg=self.colors["card"], fg=self.colors["text"]
        ).pack(side=tk.LEFT, padx=(0, 4))
        
        self.angle_var = tk.StringVar(value="--°")
        self.angle_label = tk.Label(
            deg_frame, textvariable=self.angle_var,
            font=("Segoe UI", 22, "bold"), bg=self.colors["card"], fg=self.colors["primary"]
        )
        self.angle_label.pack(side=tk.LEFT)
        
        # Radian display
        rad_frame = tk.Frame(angle_frame, bg=self.colors["card"])
        rad_frame.pack(side=tk.LEFT, padx=(16, 0))
        
        tk.Label(
            rad_frame, text="弧度:", font=("Segoe UI", 10),
            bg=self.colors["card"], fg=self.colors["text"]
        ).pack(side=tk.LEFT, padx=(0, 4))
        
        self.radian_var = tk.StringVar(value="-- rad")
        self.radian_label = tk.Label(
            rad_frame, textvariable=self.radian_var,
            font=("Segoe UI", 22, "bold"), bg=self.colors["card"], fg="#8b5cf6"
        )
        self.radian_label.pack(side=tk.LEFT)
        
    def setup_settings_panel(self, parent):
        settings_frame = tk.Frame(parent, bg=self.colors["card"])
        settings_frame.pack(side=tk.TOP, fill=tk.X, pady=(0, 12))
        
        inner_frame = tk.Frame(settings_frame, bg=self.colors["card"])
        inner_frame.pack(fill=tk.X, padx=16, pady=8)
        
        # Detection method
        tk.Label(
            inner_frame, text="Method:", font=("Segoe UI", 9),
            bg=self.colors["card"], fg=self.colors["text"]
        ).pack(side=tk.LEFT, padx=(0, 4))
        
        self.method_var = tk.StringVar(value="auto")
        methods = [("Auto", "auto"), ("Canny", "canny"), ("Sobel", "sobel"), ("LSD", "lsd")]
        for text, value in methods:
            tk.Radiobutton(
                inner_frame, text=text, variable=self.method_var, value=value,
                font=("Segoe UI", 9), bg=self.colors["card"], fg=self.colors["text"],
                selectcolor=self.colors["bg"], activebackground=self.colors["card"]
            ).pack(side=tk.LEFT, padx=4)
        
        # Threshold
        tk.Label(
            inner_frame, text="  Threshold:", font=("Segoe UI", 9),
            bg=self.colors["card"], fg=self.colors["text"]
        ).pack(side=tk.LEFT, padx=(16, 4))
        
        self.threshold_var = tk.IntVar(value=50)
        tk.Scale(
            inner_frame, from_=10, to=150, orient=tk.HORIZONTAL,
            variable=self.threshold_var, length=100,
            font=("Segoe UI", 8), bg=self.colors["card"], fg=self.colors["text"],
            highlightthickness=0
        ).pack(side=tk.LEFT, padx=(0, 16))
        
        # Rect indicators
        self.rect1_label = tk.Label(
            inner_frame, text="◇ Rect 1: --", font=("Segoe UI", 9),
            bg=self.colors["card"], fg=self.colors["rect1"]
        )
        self.rect1_label.pack(side=tk.RIGHT, padx=(0, 12))
        
        self.rect2_label = tk.Label(
            inner_frame, text="◇ Rect 2: --", font=("Segoe UI", 9),
            bg=self.colors["card"], fg=self.colors["rect2"]
        )
        self.rect2_label.pack(side=tk.RIGHT)
        
    def setup_canvas(self, parent):
        canvas_container = tk.Frame(parent, bg=self.colors["card"])
        canvas_container.pack(fill=tk.BOTH, expand=True)
        
        # Instructions
        instructions_frame = tk.Frame(canvas_container, bg=self.colors["card"])
        instructions_frame.pack(fill=tk.X, padx=16, pady=(12, 0))
        
        self.instructions_label = tk.Label(
            instructions_frame,
            text="💡 Click point 1 → Click point 2 (edge direction) → Drag point 3 (width) | Scroll to zoom | Right-drag to pan",
            font=("Segoe UI", 9), bg=self.colors["card"], fg=self.colors["muted"]
        )
        self.instructions_label.pack(side=tk.LEFT)
        
        # Canvas
        canvas_frame = tk.Frame(canvas_container, bg="#e2e8f0", padx=1, pady=1)
        canvas_frame.pack(fill=tk.BOTH, expand=True, padx=16, pady=12)
        
        self.canvas = tk.Canvas(
            canvas_frame, bg="#1e293b", highlightthickness=0
        )
        self.canvas.pack(fill=tk.BOTH, expand=True)
        
        # Bind events
        self.canvas.bind("<Button-1>", self.on_left_click)
        self.canvas.bind("<Motion>", self.on_mouse_move)
        self.canvas.bind("<ButtonRelease-1>", self.on_left_release)
        self.canvas.bind("<Button-3>", self.on_right_down)  # Right click for pan
        self.canvas.bind("<B3-Motion>", self.on_right_drag)
        self.canvas.bind("<ButtonRelease-3>", self.on_right_up)
        self.canvas.bind("<MouseWheel>", self.on_mouse_wheel)  # Windows
        self.canvas.bind("<Button-4>", self.on_mouse_wheel)    # Linux scroll up
        self.canvas.bind("<Button-5>", self.on_mouse_wheel)    # Linux scroll down
        
    def setup_status_bar(self, parent):
        status_frame = tk.Frame(parent, bg=self.colors["card"])
        status_frame.pack(side=tk.BOTTOM, fill=tk.X, pady=(12, 0))
        
        self.status_var = tk.StringVar(value="Ready • Load an image to begin")
        self.status_label = tk.Label(
            status_frame, textvariable=self.status_var,
            font=("Segoe UI", 9), bg=self.colors["card"], fg=self.colors["muted"],
            anchor=tk.W, padx=16, pady=8
        )
        self.status_label.pack(fill=tk.X)
        
    # ==================== Zoom and Pan ====================
    
    def screen_to_image(self, sx, sy):
        """Convert screen coordinates to original image coordinates"""
        if not self.original_image:
            return None
        img_w, img_h = self.original_image.size
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        # Account for centering
        display_w = img_w * self.zoom_level
        display_h = img_h * self.zoom_level
        offset_x = (canvas_w - display_w) / 2 + self.pan_x
        offset_y = (canvas_h - display_h) / 2 + self.pan_y
        
        ix = (sx - offset_x) / self.zoom_level
        iy = (sy - offset_y) / self.zoom_level
        return (ix, iy)
        
    def image_to_screen(self, ix, iy):
        """Convert original image coordinates to screen coordinates"""
        if not self.original_image:
            return None
        img_w, img_h = self.original_image.size
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        display_w = img_w * self.zoom_level
        display_h = img_h * self.zoom_level
        offset_x = (canvas_w - display_w) / 2 + self.pan_x
        offset_y = (canvas_h - display_h) / 2 + self.pan_y
        
        sx = ix * self.zoom_level + offset_x
        sy = iy * self.zoom_level + offset_y
        return (sx, sy)
        
    def zoom_in(self):
        self.set_zoom(self.zoom_level * 1.25)
        
    def zoom_out(self):
        self.set_zoom(self.zoom_level / 1.25)
        
    def reset_zoom(self):
        self.zoom_level = 1.0
        self.pan_x = 0
        self.pan_y = 0
        self.zoom_label.config(text="100%")
        # Clear cache
        self.cached_zoom_level = None
        self.cached_image = None
        self.redraw_canvas()
        
    def set_zoom(self, level):
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, level))
        self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
        self.redraw_canvas()
        
    def on_mouse_wheel(self, event):
        """Handle mouse wheel for zoom"""
        # Determine zoom direction
        # Linux: event.num 4 = scroll up, 5 = scroll down
        # Windows: event.delta positive = scroll up
        zoom_in = False
        
        if hasattr(event, 'delta') and event.delta != 0:  # Windows
            zoom_in = event.delta > 0
        elif event.num == 4:  # Linux scroll up
            zoom_in = True
        elif event.num == 5:  # Linux scroll down
            zoom_in = False
        else:
            return  # Unknown event
            
        # Apply zoom
        if zoom_in:
            self.zoom_level *= 1.15
        else:
            self.zoom_level /= 1.15
            
        self.zoom_level = max(self.min_zoom, min(self.max_zoom, self.zoom_level))
        self.zoom_label.config(text=f"{int(self.zoom_level * 100)}%")
        self.redraw_canvas()
        
    def on_right_down(self, event):
        self.panning = True
        self.pan_start = (event.x, event.y)
        
    def on_right_drag(self, event):
        if self.panning:
            dx = event.x - self.pan_start[0]
            dy = event.y - self.pan_start[1]
            self.pan_x += dx
            self.pan_y += dy
            self.pan_start = (event.x, event.y)
            self.redraw_canvas()
            
    def on_right_up(self, event):
        self.panning = False
        
    # ==================== Image Loading ====================
    
    def load_image(self):
        file_path = filedialog.askopenfilename(
            title="Select Image",
            filetypes=[
                ("Image files", "*.png *.jpg *.jpeg *.bmp *.gif *.tiff *.webp"),
                ("All files", "*.*")
            ]
        )
        
        if file_path:
            self.image_path = file_path
            self.original_image = Image.open(file_path).convert("RGB")
            self.reset_zoom()
            self.clear_all()
            self.status_var.set(f"✓ Loaded: {os.path.basename(file_path)} • Scroll to zoom, right-drag to pan")
            
    def redraw_canvas(self):
        """Redraw the canvas with current zoom and pan"""
        if not self.original_image:
            return
            
        self.canvas.delete("all")
        
        # Get canvas size
        canvas_w = self.canvas.winfo_width()
        canvas_h = self.canvas.winfo_height()
        
        if canvas_w < 10 or canvas_h < 10:
            self.root.after(100, self.redraw_canvas)
            return
            
        # Calculate display size
        img_w, img_h = self.original_image.size
        display_w = int(img_w * self.zoom_level)
        display_h = int(img_h * self.zoom_level)
        
        # Use cached image if zoom level matches, otherwise resize
        if self.cached_zoom_level == self.zoom_level and self.cached_image is not None:
            self.display_image = self.cached_image
        elif display_w > 0 and display_h > 0:
            # Use BILINEAR for faster resizing (much faster than LANCZOS)
            self.display_image = self.original_image.resize(
                (display_w, display_h), 
                Image.Resampling.BILINEAR
            )
            self.cached_image = self.display_image
            self.cached_zoom_level = self.zoom_level
            
        if self.display_image:
            self.tk_image = ImageTk.PhotoImage(self.display_image)
            
            # Center with pan offset
            x = (canvas_w - display_w) // 2 + self.pan_x
            y = (canvas_h - display_h) // 2 + self.pan_y
            
            self.canvas.create_image(x, y, anchor=tk.NW, image=self.tk_image, tags="image")
        
        # Redraw rectangles and lines
        for i, rect in enumerate(self.rectangles):
            self.draw_rotated_rect(rect, i + 1)
        for i, line in enumerate(self.detected_lines):
            self.draw_detected_line(line, i + 1)
            
        # Draw preview
        if self.current_rect_points:
            self.draw_preview()
            
    # ==================== Rectangle Drawing ====================
    
    def on_left_click(self, event):
        if not self.original_image:
            messagebox.showwarning("No Image", "Please load an image first!")
            return
            
        # Check if in adjust mode and clicking on a line endpoint
        if self.adjust_mode and self.detected_lines:
            hit_info = self.hit_test_line_endpoint(event.x, event.y)
            if hit_info:
                self.selected_line_idx, self.selected_point_idx = hit_info
                self.dragging = True
                self.drag_start = self.screen_to_image(event.x, event.y)
                self.status_var.set(f"Dragging endpoint {self.selected_point_idx + 1} of Line {self.selected_line_idx + 1}")
                return
        
        if len(self.rectangles) >= 2:
            messagebox.showinfo("Info", "Maximum 2 rectangles. Clear to draw new ones.")
            return
            
        # Convert to image coordinates
        img_pos = self.screen_to_image(event.x, event.y)
        if not img_pos:
            return
        x, y = img_pos
        
        if len(self.current_rect_points) == 0:
            self.current_rect_points.append((x, y))
            self.drawing_step = 1
            self.status_var.set(f"Point 1: ({int(x)}, {int(y)}) • Click to set second point")
        elif len(self.current_rect_points) == 1:
            p1 = self.current_rect_points[0]
            dist = math.sqrt((x - p1[0])**2 + (y - p1[1])**2)
            if dist < 10:
                self.status_var.set("⚠️ Points too close • Click further away")
                return
            self.current_rect_points.append((x, y))
            self.drawing_step = 2
            self.status_var.set(f"Direction set • Drag to define rectangle width")
            
    def on_mouse_move(self, event):
        # Handle line endpoint dragging in adjust mode
        if self.dragging and self.selected_line_idx is not None:
            img_pos = self.screen_to_image(event.x, event.y)
            if img_pos:
                # Update the endpoint position
                line = self.detected_lines[self.selected_line_idx]
                p1, p2 = line[0]
                if self.selected_point_idx == 0:
                    new_p1 = img_pos
                    self.detected_lines[self.selected_line_idx] = [(new_p1, p2)]
                else:
                    new_p2 = img_pos
                    self.detected_lines[self.selected_line_idx] = [(p1, new_p2)]
                self.redraw_canvas()
                # Update angle display in real-time
                if len(self.detected_lines) >= 2:
                    self.update_angle_display()
            return
            
        if not self.current_rect_points or not self.original_image:
            return
            
        img_pos = self.screen_to_image(event.x, event.y)
        if not img_pos:
            return
            
        self.draw_preview_at(img_pos)
        
    def draw_preview_at(self, mouse_pos):
        """Draw preview at current mouse position"""
        self.canvas.delete("preview")
        
        color = self.colors["rect1"] if len(self.rectangles) == 0 else self.colors["rect2"]
        
        if len(self.current_rect_points) == 1:
            p1 = self.current_rect_points[0]
            s1 = self.image_to_screen(p1[0], p1[1])
            s2 = self.image_to_screen(mouse_pos[0], mouse_pos[1])
            if s1 and s2:
                self.canvas.create_line(s1[0], s1[1], s2[0], s2[1], fill=color, width=1, dash=(6, 4), tags="preview")
                # Small transparent point with outline
                self.canvas.create_oval(s1[0]-3, s1[1]-3, s1[0]+3, s1[1]+3, 
                    fill="", outline=color, width=1, tags="preview")
                self.canvas.create_oval(s1[0]-1, s1[1]-1, s1[0]+1, s1[1]+1, 
                    fill=color, outline="", tags="preview")
                
        elif len(self.current_rect_points) == 2:
            corners = self.calculate_rotated_rect(self.current_rect_points[0], self.current_rect_points[1], mouse_pos)
            if corners:
                screen_corners = [self.image_to_screen(c[0], c[1]) for c in corners]
                if all(screen_corners):
                    points = []
                    for sc in screen_corners:
                        points.extend([sc[0], sc[1]])
                    # High transparency preview
                    self.canvas.create_polygon(points, outline=color, fill="", 
                        width=1, dash=(6, 4), tags="preview")
                    for p in self.current_rect_points:
                        sp = self.image_to_screen(p[0], p[1])
                        if sp:
                            # Small outline-only points
                            self.canvas.create_oval(sp[0]-3, sp[1]-3, sp[0]+3, sp[1]+3, 
                                fill="", outline=color, width=1, tags="preview")
                            self.canvas.create_oval(sp[0]-1, sp[1]-1, sp[0]+1, sp[1]+1, 
                                fill=color, outline="", tags="preview")
                            
    def on_left_release(self, event):
        # Handle line dragging end
        if self.dragging:
            self.dragging = False
            self.selected_line_idx = None
            self.selected_point_idx = None
            self.drag_start = None
            if len(self.detected_lines) >= 2:
                self.status_var.set("✓ Line adjusted • Angle updated")
            return
            
        if len(self.current_rect_points) == 2:
            img_pos = self.screen_to_image(event.x, event.y)
            if not img_pos:
                return
                
            corners = self.calculate_rotated_rect(self.current_rect_points[0], self.current_rect_points[1], img_pos)
            if corners:
                p1, p2 = self.current_rect_points[0], self.current_rect_points[1]
                dx, dy = p2[0] - p1[0], p2[1] - p1[1]
                length = math.sqrt(dx*dx + dy*dy)
                if length > 0:
                    nx, ny = -dy/length, dx/length
                    width = abs((img_pos[0] - p1[0]) * nx + (img_pos[1] - p1[1]) * ny)
                    
                    if width > 5:
                        self.rectangles.append(corners)
                        self.current_rect_points = []
                        self.drawing_step = 0
                        self.canvas.delete("preview")
                        self.update_rect_indicators()
                        self.redraw_canvas()
                        
                        if len(self.rectangles) >= 2:
                            self.detect_btn.config(state=tk.NORMAL)
                            self.status_var.set("✓ Two rectangles drawn • Click 'Detect Lines'")
                        else:
                            self.status_var.set(f"✓ Rectangle {len(self.rectangles)} drawn • Draw one more")
                            
    def calculate_rotated_rect(self, p1, p2, p3):
        x1, y1 = p1
        x2, y2 = p2
        x3, y3 = p3
        
        dx, dy = x2 - x1, y2 - y1
        length = math.sqrt(dx*dx + dy*dy)
        if length < 1:
            return None
            
        ux, uy = dx/length, dy/length
        px, py = -uy, ux
        width = (x3 - x1) * px + (y3 - y1) * py
        
        return [
            (x1, y1),
            (x2, y2),
            (x2 + width * px, y2 + width * py),
            (x1 + width * px, y1 + width * py)
        ]
        
    def draw_rotated_rect(self, corners, rect_num):
        colors = [self.colors["rect1"], self.colors["rect2"]]
        color = colors[(rect_num - 1) % 2]
        
        screen_corners = [self.image_to_screen(c[0], c[1]) for c in corners]
        if not all(screen_corners):
            return
            
        points = []
        for sc in screen_corners:
            points.extend([sc[0], sc[1]])
            
        # High transparency rectangle with stipple pattern
        self.canvas.create_polygon(points, outline=color, fill=color, width=1, 
            stipple="gray12", tags=f"rect_{rect_num}")
        
        # Small outline-only corner points
        for c in screen_corners:
            self.canvas.create_oval(c[0]-3, c[1]-3, c[0]+3, c[1]+3, 
                fill="", outline=color, width=1, tags=f"rect_{rect_num}")
            # Tiny center dot
            self.canvas.create_oval(c[0]-1, c[1]-1, c[0]+1, c[1]+1, 
                fill=color, outline="", tags=f"rect_{rect_num}")
            
        cx = sum(c[0] for c in screen_corners) / 4
        cy = sum(c[1] for c in screen_corners) / 4
        self.canvas.create_text(cx, cy, text=f"#{rect_num}", fill=color, font=("Segoe UI", 9, "bold"), tags=f"rect_{rect_num}")
        
    def update_rect_indicators(self):
        self.rect1_label.config(text="◆ Rect 1: ✓" if len(self.rectangles) >= 1 else "◇ Rect 1: --")
        self.rect2_label.config(text="◆ Rect 2: ✓" if len(self.rectangles) >= 2 else "◇ Rect 2: --")
        
    # ==================== Line Detection ====================
    
    def detect_all_lines(self):
        if not CV2_AVAILABLE:
            messagebox.showerror("Error", "OpenCV is not installed!")
            return
        if len(self.rectangles) < 2:
            messagebox.showwarning("Warning", "Please draw 2 rectangles first!")
            return
            
        self.detected_lines = []
        for i in range(1, 3):
            self.canvas.delete(f"line_{i}")
        self.canvas.delete("angle_text")
        
        success = True
        for i, corners in enumerate(self.rectangles):
            line = self.detect_line_in_rect(corners, i + 1)
            if line:
                self.detected_lines.append(line)
                self.draw_detected_line(line, i + 1)
            else:
                messagebox.showwarning(
                    "Detection Failed",
                    f"No line detected in Rectangle {i + 1}.\n\n"
                    f"Tips:\n"
                    f"• Try a different detection method\n"
                    f"• Adjust the threshold\n"
                    f"• Draw a larger/smaller rectangle\n"
                    f"• Ensure the object has clear edges"
                )
                success = False
                break
                
        if success and len(self.detected_lines) >= 2:
            self.measure_btn.config(state=tk.NORMAL)
            self.adjust_btn.config(state=tk.NORMAL)
            self.status_var.set("✓ Lines detected • Click 'Measure Angle' or 'Adjust Lines'")
            
    def detect_line_in_rect(self, corners, rect_num):
        """Detect line using multiple strategies"""
        # Get bounding box
        xs = [c[0] for c in corners]
        ys = [c[1] for c in corners]
        min_x, max_x = int(min(xs)), int(max(xs))
        min_y, max_y = int(min(ys)), int(max(ys))
        
        img_w, img_h = self.original_image.size
        min_x = max(0, min_x)
        min_y = max(0, min_y)
        max_x = min(img_w, max_x)
        max_y = min(img_h, max_y)
        
        if max_x <= min_x or max_y <= min_y:
            return None
            
        # Crop region
        region = self.original_image.crop((min_x, min_y, max_x, max_y))
        cv_image = cv2.cvtColor(np.array(region), cv2.COLOR_RGB2BGR)
        
        # Create mask for rotated rect
        mask = Image.new('L', (max_x - min_x, max_y - min_y), 0)
        draw = ImageDraw.Draw(mask)
        mask_corners = [(c[0] - min_x, c[1] - min_y) for c in corners]
        draw.polygon(mask_corners, fill=255)
        cv_mask = np.array(mask)
        
        # Try different detection methods
        method = self.method_var.get()
        threshold = self.threshold_var.get()
        
        lines = None
        
        if method == "auto":
            # Try methods in order of reliability
            lines = self.detect_lines_lsd(cv_image, cv_mask)
            if lines is None or len(lines) == 0:
                lines = self.detect_lines_canny(cv_image, cv_mask, threshold)
            if lines is None or len(lines) == 0:
                lines = self.detect_lines_sobel(cv_image, cv_mask, threshold)
        elif method == "canny":
            lines = self.detect_lines_canny(cv_image, cv_mask, threshold)
        elif method == "sobel":
            lines = self.detect_lines_sobel(cv_image, cv_mask, threshold)
        elif method == "lsd":
            lines = self.detect_lines_lsd(cv_image, cv_mask)
            
        if lines is None or len(lines) == 0:
            return None
            
        # Find longest line
        longest = max(lines, key=lambda l: math.sqrt((l[2]-l[0])**2 + (l[3]-l[1])**2))
        x1, y1, x2, y2 = longest
        
        # Convert back to original image coordinates
        return [((x1 + min_x, y1 + min_y), (x2 + min_x, y2 + min_y))]
        
    def detect_lines_canny(self, cv_image, mask, threshold):
        """Detect lines using Canny edge detection"""
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        edges = cv2.Canny(blurred, threshold * 0.4, threshold)
        edges = cv2.bitwise_and(edges, edges, mask=mask)
        
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi/180, threshold=threshold,
            minLineLength=15, maxLineGap=8
        )
        
        if lines is not None:
            return [l[0] for l in lines]
        return None
        
    def detect_lines_sobel(self, cv_image, mask, threshold):
        """Detect lines using Sobel edge detection"""
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        blurred = cv2.GaussianBlur(gray, (5, 5), 0)
        
        grad_x = cv2.Sobel(blurred, cv2.CV_64F, 1, 0, ksize=3)
        grad_y = cv2.Sobel(blurred, cv2.CV_64F, 0, 1, ksize=3)
        magnitude = np.sqrt(grad_x**2 + grad_y**2)
        
        # Normalize and threshold
        magnitude = (magnitude / magnitude.max() * 255).astype(np.uint8)
        _, edges = cv2.threshold(magnitude, threshold, 255, cv2.THRESH_BINARY)
        edges = cv2.bitwise_and(edges, edges, mask=mask)
        
        lines = cv2.HoughLinesP(
            edges, rho=1, theta=np.pi/180, threshold=threshold,
            minLineLength=15, maxLineGap=8
        )
        
        if lines is not None:
            return [l[0] for l in lines]
        return None
        
    def detect_lines_lsd(self, cv_image, mask):
        """Detect lines using LSD (Line Segment Detector)"""
        gray = cv2.cvtColor(cv_image, cv2.COLOR_BGR2GRAY)
        
        # Create LSD detector
        lsd = cv2.createLineSegmentDetector(cv2.LSD_REFINE_STD)
        result = lsd.detect(gray)
        # Handle different OpenCV versions
        if isinstance(result, tuple):
            lines = result[0]
        else:
            lines = result
        
        if lines is not None and len(lines) > 0:
            # Filter by mask
            filtered = []
            for line in lines:
                x1, y1, x2, y2 = map(int, line[0])
                # Check if line is within mask
                if 0 <= y1 < mask.shape[0] and 0 <= x1 < mask.shape[1]:
                    if 0 <= y2 < mask.shape[0] and 0 <= x2 < mask.shape[1]:
                        if mask[y1, x1] > 0 and mask[y2, x2] > 0:
                            filtered.append([x1, y1, x2, y2])
            return filtered if filtered else None
        return None
        
    def draw_detected_line(self, line, line_num):
        colors = [self.colors["line1"], self.colors["line2"]]
        color = colors[(line_num - 1) % 2]
        
        p1, p2 = line[0]
        s1 = self.image_to_screen(p1[0], p1[1])
        s2 = self.image_to_screen(p2[0], p2[1])
        
        if not s1 or not s2:
            return
            
        # Draw high transparency line with stipple pattern
        self.canvas.create_line(s1[0], s1[1], s2[0], s2[1], fill=color, width=3, 
            stipple="gray12", tags=f"line_{line_num}")
        # Draw thin solid outline for visibility
        self.canvas.create_line(s1[0], s1[1], s2[0], s2[1], fill=color, width=1, 
            tags=f"line_{line_num}")
        
        # Draw endpoints - slightly larger in adjust mode, all transparent
        if self.adjust_mode:
            # Smaller, transparent endpoints for adjustment (no labels)
            for idx, s in enumerate([s1, s2]):
                # Outer ring (transparent)
                self.canvas.create_oval(s[0]-8, s[1]-8, s[0]+8, s[1]+8, 
                    fill="", outline=color, width=1, tags=f"line_{line_num}")
                # Inner ring (high transparency)
                self.canvas.create_oval(s[0]-5, s[1]-5, s[0]+5, s[1]+5, 
                    fill=color, outline="", stipple="gray12", tags=f"line_{line_num}")
                # Center dot (also transparent)
                self.canvas.create_oval(s[0]-1, s[1]-1, s[0]+1, s[1]+1, 
                    fill=color, outline="", stipple="gray25", tags=f"line_{line_num}")
        else:
            # Normal display - small transparent endpoints
            for s in [s1, s2]:
                # Outer ring
                self.canvas.create_oval(s[0]-6, s[1]-6, s[0]+6, s[1]+6, 
                    fill="", outline=color, width=1, tags=f"line_{line_num}")
                # High transparency inner
                self.canvas.create_oval(s[0]-4, s[1]-4, s[0]+4, s[1]+4, 
                    fill=color, outline="", stipple="gray12", tags=f"line_{line_num}")
                # Center dot for precision
                self.canvas.create_oval(s[0]-1, s[1]-1, s[0]+1, s[1]+1, 
                    fill=color, outline="", tags=f"line_{line_num}")
            
    # ==================== Angle Measurement ====================
    
    def measure_angle(self):
        if len(self.detected_lines) < 2:
            messagebox.showwarning("Warning", "Please detect 2 lines first!")
            return
            
        line1 = self.detected_lines[0][0]
        line2 = self.detected_lines[1][0]
        
        v1 = (line1[1][0] - line1[0][0], line1[1][1] - line1[0][1])
        v2 = (line2[1][0] - line2[0][0], line2[1][1] - line2[0][1])
        
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
        
        if mag1 == 0 or mag2 == 0:
            messagebox.showerror("Error", "Invalid line!")
            return
            
        cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
        angle_deg = math.degrees(math.acos(cos_angle))
        angle_rad = math.acos(cos_angle)
        supp_deg = 180 - angle_deg
        supp_rad = math.pi - angle_rad
        
        self.angle_var.set(f"{angle_deg:.1f}°")
        self.radian_var.set(f"{angle_rad:.3f} rad")
        self.angle_label.config(fg=self.colors["secondary"])
        
        self.status_var.set(f"📐 角度: {angle_deg:.2f}° ({angle_rad:.3f} rad) • 补角: {supp_deg:.2f}° ({supp_rad:.3f} rad)")
        
        messagebox.showinfo(
            "📐 测量结果",
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
            f"  角度: {angle_deg:.2f}°  ({angle_rad:.3f} rad)\n"
            f"  补角: {supp_deg:.2f}°  ({supp_rad:.3f} rad)\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
        )
        
    # ==================== Line Adjustment ====================
    
    def toggle_adjust_mode(self):
        """Toggle line adjustment mode"""
        self.adjust_mode = not self.adjust_mode
        if self.adjust_mode:
            self.adjust_btn.config(text="✏️ Done Adjusting", bg=self.colors["accent"])
            self.instructions_label.config(
                text="✏️ ADJUST MODE: Click and drag line endpoints to adjust | Click 'Done Adjusting' when finished"
            )
            self.status_var.set("Adjust mode ON • Drag line endpoints to adjust positions")
        else:
            self.adjust_btn.config(text="✏️ Adjust Lines", bg="#8b5cf6")
            self.instructions_label.config(
                text="💡 Click point 1 → Click point 2 (edge direction) → Drag point 3 (width) | Scroll to zoom | Right-drag to pan"
            )
            self.status_var.set("Adjust mode OFF • Lines locked")
        self.redraw_canvas()
        
    def hit_test_line_endpoint(self, sx, sy, radius=15):
        """Check if screen coordinates hit a line endpoint. Returns (line_idx, point_idx) or None"""
        for i, line in enumerate(self.detected_lines):
            p1, p2 = line[0]
            for j, p in enumerate([p1, p2]):
                sp = self.image_to_screen(p[0], p[1])
                if sp:
                    dist = math.sqrt((sx - sp[0])**2 + (sy - sp[1])**2)
                    if dist <= radius:
                        return (i, j)
        return None
        
    def update_angle_display(self):
        """Update angle display based on current line positions"""
        if len(self.detected_lines) < 2:
            return
            
        line1 = self.detected_lines[0][0]
        line2 = self.detected_lines[1][0]
        
        v1 = (line1[1][0] - line1[0][0], line1[1][1] - line1[0][1])
        v2 = (line2[1][0] - line2[0][0], line2[1][1] - line2[0][1])
        
        dot = v1[0] * v2[0] + v1[1] * v2[1]
        mag1 = math.sqrt(v1[0]**2 + v1[1]**2)
        mag2 = math.sqrt(v2[0]**2 + v2[1]**2)
        
        if mag1 == 0 or mag2 == 0:
            self.angle_var.set("--°")
            return
            
        cos_angle = max(-1, min(1, dot / (mag1 * mag2)))
        angle_deg = math.degrees(math.acos(cos_angle))
        angle_rad = math.acos(cos_angle)
        supp_deg = 180 - angle_deg
        supp_rad = math.pi - angle_rad
        
        self.angle_var.set(f"{angle_deg:.1f}°")
        self.radian_var.set(f"{angle_rad:.3f} rad")
        self.status_var.set(f"📐 角度: {angle_deg:.2f}° ({angle_rad:.3f} rad) • 补角: {supp_deg:.2f}° ({supp_rad:.3f} rad)")
        
    # ==================== Clear ====================
    
    def clear_all(self):
        self.rectangles = []
        self.detected_lines = []
        self.current_rect_points = []
        self.drawing_step = 0
        self.adjust_mode = False
        self.selected_line_idx = None
        self.selected_point_idx = None
        self.dragging = False
        
        for i in range(1, 3):
            self.canvas.delete(f"rect_{i}")
            self.canvas.delete(f"line_{i}")
        self.canvas.delete("preview")
        self.canvas.delete("angle_text")
        
        self.angle_var.set("--°")
        self.radian_var.set("-- rad")
        self.angle_label.config(fg=self.colors["primary"])
        self.detect_btn.config(state=tk.DISABLED)
        self.measure_btn.config(state=tk.DISABLED)
        self.adjust_btn.config(state=tk.DISABLED, text="✏️ Adjust Lines", bg="#8b5cf6")
        self.adjust_mode = False
        self.update_rect_indicators()
        self.status_var.set("✓ 已清除 • 点击绘制矩形")


def main():
    root = tk.Tk()
    root.geometry("1200x850")
    root.minsize(900, 650)
    
    app = LineDetectorApp(root)
    root.mainloop()


if __name__ == "__main__":
    main()