import cv2
import mediapipe as mp
import numpy as np
import random
import time
import math
from collections import deque
import streamlit as st
from streamlit_webrtc import webrtc_streamer, VideoTransformerBase, RTCConfiguration

# ----------------------------------------------------------------------
# Config
# ----------------------------------------------------------------------
WIDTH, HEIGHT = 640, 480  # Optimized web streaming size
GRAVITY = 0.55
TRAIL_LENGTH = 18
MAX_LIVES = 3
INITIAL_SPAWN_INTERVAL = 1.2
MIN_SPAWN_INTERVAL = 0.45

FRUIT_CONFIG = {
    "apple":      {"color": (60, 60, 220),   "juice": (50, 50, 200),   "radius": 38, "points": 1},
    "orange":     {"color": (0, 140, 255),   "juice": (0, 120, 230),   "radius": 36, "points": 1},
    "watermelon": {"color": (60, 180, 60),   "juice": (180, 30, 30),   "radius": 48, "points": 2},
    "lemon":      {"color": (20, 220, 240),  "juice": (20, 200, 220),  "radius": 30, "points": 1},
    "plum":       {"color": (160, 50, 120),  "juice": (140, 40, 110),  "radius": 32, "points": 1},
    "bomb":       {"color": (30, 30, 30),    "juice": (0, 0, 0),       "radius": 40, "points": 0},
}
FRUIT_WEIGHTS = {"apple": 3, "orange": 3, "watermelon": 2, "lemon": 3, "plum": 3, "bomb": 1}

def point_segment_distance(px, py, x1, y1, x2, y2):
    dx, dy = x2 - x1, y2 - y1
    if dx == 0 and dy == 0:
        return math.hypot(px - x1, py - y1)
    t = ((px - x1) * dx + (py - y1) * dy) / (dx * dx + dy * dy)
    t = max(0.0, min(1.0, t))
    cx, cy = x1 + t * dx, y1 + t * dy
    return math.hypot(px - cx, py - cy)

class Fruit:
    def __init__(self, kind):
        cfg = FRUIT_CONFIG[kind]
        self.kind = kind
        self.color = cfg["color"]
        self.juice_color = cfg["juice"]
        self.radius = cfg["radius"]
        self.points = cfg["points"]
        self.is_bomb = kind == "bomb"
        self.x = float(random.randint(self.radius + 30, WIDTH - self.radius - 30))
        self.y = float(HEIGHT + self.radius)
        self.vx = random.uniform(-3.0, 3.0)
        self.vy = -random.uniform(17.0, 23.0)
        self.rotation = random.uniform(0, 360)
        self.rot_speed = random.uniform(-4, 4)
        self.sliced = False

    def update(self):
        self.vy += GRAVITY
        self.x += self.vx
        self.y += self.vy
        self.rotation += self.rot_speed

    def is_off_screen(self):
        return self.y - self.radius > HEIGHT + 50

    def draw(self, frame):
        center = (int(self.x), int(self.y))
        if self.is_bomb:
            cv2.circle(frame, center, self.radius, (25, 25, 25), -1)
            cv2.circle(frame, center, self.radius, (90, 90, 90), 3)
            fuse_base = (int(self.x), int(self.y - self.radius))
            fx = int(self.x + 14 * math.cos(math.radians(self.rotation)))
            fy = fuse_base[1] - 18
            cv2.line(frame, fuse_base, (fx, fy), (90, 60, 30), 4)
            cv2.circle(frame, (fx, fy), 5, (0, 140, 255), -1)
        else:
            cv2.circle(frame, center, self.radius, self.color, -1)
            rim = tuple(max(0, c - 70) for c in self.color)
            cv2.circle(frame, center, self.radius, rim, 3)
            hl = (int(self.x - self.radius * 0.35), int(self.y - self.radius * 0.35))
            cv2.ellipse(frame, hl, (int(self.radius * 0.28), int(self.radius * 0.16)),
                        30, 0, 360, (255, 255, 255), -1)

class SliceHalf:
    def __init__(self, fruit, direction):
        self.x, self.y = fruit.x, fruit.y
        self.radius = fruit.radius
        self.color = fruit.color
        self.direction = direction
        self.vx = fruit.vx + direction * 4.5 + random.uniform(-1, 1)
        self.vy = fruit.vy - 4
        self.rotation = fruit.rotation
        self.rot_speed = direction * 9
        self.life = 28
        self.max_life = self.life

    def update(self):
        self.vy += GRAVITY
        self.x += self.vx
        self.y += self.vy
        self.rotation += self.rot_speed
        self.life -= 1

    def draw(self, frame):
        if self.life <= 0:
            return
        alpha = max(0.0, self.life / self.max_life)
        center = (int(self.x), int(self.y))
        start_angle = 90 if self.direction == -1 else -90
        end_angle = start_angle + 180
        overlay = frame.copy()
        cv2.ellipse(overlay, center, (self.radius, self.radius), self.rotation,
                     start_angle, end_angle, self.color, -1)
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

class Particle:
    def __init__(self, x, y, color):
        angle = random.uniform(0, 2 * math.pi)
        speed = random.uniform(2, 9)
        self.x, self.y = x, y
        self.vx = math.cos(angle) * speed
        self.vy = math.sin(angle) * speed - 3
        self.color = color
        self.life = random.randint(14, 26)
        self.max_life = self.life
        self.radius = random.randint(2, 4)

    def update(self):
        self.vy += GRAVITY * 0.45
        self.x += self.vx
        self.y += self.vy
        self.life -= 1

    def draw(self, frame):
        if self.life <= 0:
            return
        alpha = self.life / self.max_life
        overlay = frame.copy()
        cv2.circle(overlay, (int(self.x), int(self.y)), self.radius, self.color, -1)
        cv2.addWeighted(overlay, alpha, frame, 1 - alpha, 0, frame)

class Game:
    def __init__(self):
        self.reset()

    def reset(self):
        self.fruits = []
        self.slice_halves = []
        self.particles = []
        self.score = 0
        self.lives = MAX_LIVES
        self.last_spawn = time.time()
        self.spawn_interval = INITIAL_SPAWN_INTERVAL
        self.game_over = False
        self.flash_timer = 0

    def spawn_fruit(self):
        kinds = list(FRUIT_WEIGHTS.keys())
        weights = list(FRUIT_WEIGHTS.values())
        kind = random.choices(kinds, weights=weights, k=1)[0]
        self.fruits.append(Fruit(kind))

    def update(self):
        if self.game_over:
            return
        now = time.time()
        if now - self.last_spawn > self.spawn_interval:
            self.spawn_fruit()
            self.last_spawn = now
            self.spawn_interval = max(MIN_SPAWN_INTERVAL, self.spawn_interval * 0.985)

        for f in self.fruits:
            f.update()

        missed = [f for f in self.fruits if f.is_off_screen() and not f.is_bomb]
        if missed:
            self.lives -= len(missed)
            if self.lives <= 0:
                self.lives = 0
                self.game_over = True

        self.fruits = [f for f in self.fruits if not f.is_off_screen()]

        for s in self.slice_halves:
            s.update()
        self.slice_halves = [s for s in self.slice_halves if s.life > 0]

        for p in self.particles:
            p.update()
        self.particles = [p for p in self.particles if p.life > 0]

        if self.flash_timer > 0:
            self.flash_timer -= 1

    def check_slice(self, trail_points):
        if self.game_over or len(trail_points) < 2:
            return
        to_slice = []
        for i in range(len(trail_points) - 1):
            ax, ay = trail_points[i]
            bx, by = trail_points[i + 1]
            for f in self.fruits:
                if f in to_slice:
                    continue
                dist = point_segment_distance(f.x, f.y, ax, ay, bx, by)
                if dist < f.radius:
                    to_slice.append(f)
        for f in to_slice:
            self.slice_fruit(f)
        if to_slice:
            self.fruits = [f for f in self.fruits if f not in to_slice]

    def slice_fruit(self, f):
        if f.is_bomb:
            self.game_over = True
            self.flash_timer = 8
            for _ in range(50):
                self.particles.append(Particle(f.x, f.y, (0, 90, 255)))
            return
        self.score += f.points
        self.slice_halves.append(SliceHalf(f, -1))
        self.slice_halves.append(SliceHalf(f, 1))
        for _ in range(16):
            self.particles.append(Particle(f.x, f.y, f.juice_color))

    def draw(self, frame):
        for f in self.fruits:
            f.draw(frame)
        for s in self.slice_halves:
            s.draw(frame)
        for p in self.particles:
            p.draw(frame)
        if self.flash_timer > 0:
            overlay = frame.copy()
            overlay[:] = (0, 0, 255)
            cv2.addWeighted(overlay, 0.35, frame, 0.65, 0, frame)

class HandTracker:
    def __init__(self, max_hands=1):
        self.mp_hands = mp.solutions.hands
        self.hands = self.mp_hands.Hands(
            max_num_hands=max_hands,
            min_detection_confidence=0.65,
            min_tracking_confidence=0.5,
        )

    def get_fingertips(self, frame_bgr):
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        rgb.flags.writeable = False
        results = self.hands.process(rgb)
        tips = []
        if results.multi_hand_landmarks:
            h, w = frame_bgr.shape[:2]
            for hand_landmarks in results.multi_hand_landmarks:
                lm = hand_landmarks.landmark[self.mp_hands.HandLandmark.INDEX_FINGER_TIP]
                tips.append((int(lm.x * w), int(lm.y * h)))
        return tips

    def close(self):
        self.hands.close()

def draw_trail(frame, trail):
    pts = list(trail)
    n = len(pts)
    for i in range(1, n):
        if pts[i - 1] is None or pts[i] is None:
            continue
        thickness = int(np.interp(i, [0, n], [2, 10]))
        cv2.line(frame, pts[i - 1], pts[i], (255, 255, 100), thickness, lineType=cv2.LINE_AA)
    for i in range(n):
        if pts[i] is not None and (i == n - 1):
            cv2.circle(frame, pts[i], 9, (255, 255, 255), -1)
            cv2.circle(frame, pts[i], 9, (255, 255, 100), 2)

def draw_hud(frame, game):
    cv2.rectangle(frame, (0, 0), (WIDTH, 70), (0, 0, 0), -1)
    cv2.putText(frame, f"Score: {game.score}", (20, 46),
                cv2.FONT_HERSHEY_SIMPLEX, 1.1, (255, 255, 255), 2, cv2.LINE_AA)
    for i in range(MAX_LIVES):
        cx = WIDTH - 30 - i * 42
        color = (0, 0, 255) if i < game.lives else (60, 60, 60)
        cv2.circle(frame, (cx, 35), 13, color, -1)
        cv2.circle(frame, (cx, 35), 13, (255, 255, 255), 1)

    if game.game_over:
        overlay = frame.copy()
        cv2.rectangle(overlay, (0, 0), (WIDTH, HEIGHT), (0, 0, 0), -1)
        cv2.addWeighted(overlay, 0.6, frame, 0.4, 0, frame)
        cv2.putText(frame, "GAME OVER", (WIDTH // 2 - 140, HEIGHT // 2 - 10),
                    cv2.FONT_HERSHEY_SIMPLEX, 1.5, (0, 0, 255), 3, cv2.LINE_AA)
        cv2.putText(frame, "Click 'Stop' & 'Start' to Reset", (WIDTH // 2 - 190, HEIGHT // 2 + 40),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.7, (200, 200, 200), 2, cv2.LINE_AA)

# ----------------------------------------------------------------------
# WebRTC Stream Engine
# ----------------------------------------------------------------------
RTC_CONFIGURATION = RTCConfiguration(
    {"iceServers": [{"urls": ["stun:stun.l.google.com:19302"]}]}
)

class FruitNinjaTransformer(VideoTransformerBase):
    def __init__(self):
        self.tracker = HandTracker(max_hands=1)
        self.game = Game()
        self.trail = deque(maxlen=TRAIL_LENGTH)
        self.prev_time = time.time()

    def transform(self, frame):
        img = frame.to_ndarray(format="bgr24")
        img = cv2.flip(img, 1)
        img = cv2.resize(img, (WIDTH, HEIGHT))

        tips = self.tracker.get_fingertips(img)
        if tips:
            self.trail.append(tips[0])
        else:
            self.trail.append(None)

        self.game.update()
        pts_only = [p for p in self.trail if p is not None]
        self.game.check_slice(pts_only)

        self.game.draw(img)
        draw_trail(img, self.trail)
        draw_hud(img, self.game)

        now = time.time()
        fps = 1.0 / max(1e-6, (now - self.prev_time))
        self.prev_time = now
        cv2.putText(img, f"FPS: {int(fps)}", (20, HEIGHT - 15),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (150, 150, 150), 1, cv2.LINE_AA)

        return img

# Streamlit Page Setup
st.set_page_config(page_title="Fruit Ninja AI", layout="centered")
st.title("🍓 Fruit Ninja — Web CV Edition")
st.markdown("Allow camera access and slide your **index finger** over the screen to play!")

webrtc_streamer(
    key="fruit-ninja",
    video_transformer_factory=FruitNinjaTransformer,
    rtc_configuration=RTC_CONFIGURATION,
    media_stream_constraints={"video": True, "audio": False},
)
