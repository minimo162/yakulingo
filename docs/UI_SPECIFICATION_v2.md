# ECM Translate - Next Generation UI Specification
## "Transcend" - 翻訳を超える体験

> **Design Philosophy**: 世界を変える翻訳アプリは、単なるツールを超えた「体験」でなければならない。
> Apple の「Less is More」と M3 Expressive の「感情に訴えるデザイン」を融合し、
> ユーザーが翻訳するたびに小さな感動を覚えるインターフェースを創造する。

---

## 1. Design Vision

### 1.1 Core Concept: "Transcend"

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   「言語の壁を溶かす」                                        │
│                                                             │
│   翻訳は「変換」ではなく「架け橋」                              │
│   UIはその橋を渡る体験を美しく演出する                          │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 1.2 Design Pillars (4つの柱)

| Pillar | Description | Implementation |
|--------|-------------|----------------|
| **Fluid** | 水のように流れる動き | Shape morphing, liquid transitions |
| **Breathing** | 生命感のあるUI | Ambient animations, organic motion |
| **Delightful** | 予想を超える喜び | Micro-interactions, celebration moments |
| **Invisible** | 存在を感じさせない機能性 | Zero-friction UX, anticipatory design |

---

## 2. Visual Identity

### 2.1 Color System - "Aurora Spectrum"

M3 Expressive の Dynamic Color を参考に、時間帯と操作状態に応じて変化するカラーシステム。

```python
@dataclass
class ColorSystem:
    """Dynamic color system with emotional intelligence"""

    # === Primary Palette - "Cosmic Night" ===
    bg_void: str = "#08080C"           # 深宇宙 - 究極のダーク
    bg_space: str = "#0D0D14"          # 宇宙空間
    bg_nebula: str = "#14141E"         # 星雲のベース
    bg_surface: str = "#1A1A28"        # サーフェス
    bg_elevated: str = "#242436"       # 浮遊する面
    bg_floating: str = "#2E2E44"       # 最上位の面

    # === Accent Colors - "Prismatic Light" ===
    # Primary - 翻訳の「完了」と「成功」
    accent_primary: str = "#00F5D4"    # シアン - デジタルな輝き
    accent_primary_soft: str = "#00D4B8"
    accent_primary_dim: str = "#00A896"

    # Secondary - 「進行中」と「アクション」
    accent_secondary: str = "#7B61FF"  # バイオレット - 神秘的
    accent_secondary_soft: str = "#9D8CFF"

    # Tertiary - 「警告」と「注意」
    accent_warning: str = "#FFB800"    # ゴールド - 価値ある警告
    accent_error: str = "#FF4D6A"      # ローズ - 優雅なエラー

    # === Text Hierarchy ===
    text_primary: str = "#FFFFFF"
    text_secondary: str = "#B8B8CC"
    text_tertiary: str = "#7878A0"
    text_disabled: str = "#484868"

    # === Gradient Presets - "Northern Lights" ===
    gradient_aurora: tuple = ("#00F5D4", "#7B61FF", "#FF4D6A")
    gradient_success: tuple = ("#00F5D4", "#00D4B8")
    gradient_progress: tuple = ("#7B61FF", "#00F5D4")
    gradient_surface: tuple = ("#1A1A28", "#14141E")
```

### 2.2 Typography System - "Voice"

```python
@dataclass
class Typography:
    """Typography that speaks"""

    # === Font Stack ===
    # Japanese: システムフォントを活用した可読性重視
    font_japanese: tuple = (
        "Hiragino Kaku Gothic ProN",  # macOS
        "Yu Gothic UI",                # Windows 11
        "Noto Sans JP",                # Cross-platform
        "sans-serif"
    )

    # Latin: モダンでクリーンなサンセリフ
    font_latin: tuple = (
        "SF Pro Display",              # macOS
        "Segoe UI Variable",           # Windows 11
        "Inter",                       # Cross-platform
        "sans-serif"
    )

    # Monospace: コード・技術情報用
    font_mono: tuple = (
        "SF Mono",
        "Cascadia Code",
        "JetBrains Mono",
        "monospace"
    )

    # === Type Scale (Fluid) ===
    # Based on 1.25 ratio (Major Third)
    display_hero: int = 64      # 英雄的な瞬間
    display_large: int = 48     # 大見出し
    display_medium: int = 36    # 中見出し

    title_large: int = 28       # タイトル
    title_medium: int = 22      # サブタイトル
    title_small: int = 18       # セクション

    body_large: int = 16        # 本文（強調）
    body_medium: int = 14       # 本文
    body_small: int = 12        # 補足

    label: int = 11             # ラベル
    caption: int = 10           # キャプション
```

### 2.3 Shape Language - "Organic Flow"

M3 Expressive の 35 新シェイプを参考に、有機的で流動的な形状システム。

```python
@dataclass
class ShapeSystem:
    """Shapes that feel alive"""

    # === Corner Radius Scale (10段階) ===
    radius_none: int = 0        # シャープ（アクセント用）
    radius_xs: int = 4          # ミニマル
    radius_sm: int = 8          # 小さな要素
    radius_md: int = 12         # 標準
    radius_lg: int = 16         # カード
    radius_xl: int = 24         # 大きなカード
    radius_2xl: int = 32        # モーダル
    radius_3xl: int = 48        # ヒーローエリア
    radius_full: int = 9999     # 完全な丸

    # === Shape Morphing Presets ===
    # 状態変化時にシェイプがスムーズに変形
    morph_idle_to_active = {
        "from": "rounded_rectangle",  # radius_lg
        "to": "squircle",            # より有機的な角
        "duration": 300,
        "easing": "spring(tension=300, friction=20)"
    }

    # === Squircle Formula (iOS inspired) ===
    # 標準の角丸ではなく、連続曲率のスーパー楕円
    squircle_exponent: float = 4.0  # Higher = more square
```

### 2.4 Spacing System - "Breath"

```python
@dataclass
class SpacingSystem:
    """Spacing that breathes"""

    # === Base Unit: 4px ===
    unit: int = 4

    # === Spacing Scale ===
    space_0: int = 0
    space_1: int = 4       # 1 unit  - 密接
    space_2: int = 8       # 2 units - タイト
    space_3: int = 12      # 3 units - コンパクト
    space_4: int = 16      # 4 units - 標準
    space_5: int = 20      # 5 units - 余裕
    space_6: int = 24      # 6 units - リラックス
    space_8: int = 32      # 8 units - ゆったり
    space_10: int = 40     # 10 units - 広々
    space_12: int = 48     # 12 units - 開放的
    space_16: int = 64     # 16 units - ヒーロー
    space_20: int = 80     # 20 units - 劇的
    space_24: int = 96     # 24 units - ステートメント
```

---

## 3. Motion Design - "Liquid Physics"

### 3.1 Animation Philosophy

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   「全ての動きに意味がある」                                   │
│                                                             │
│   • 速すぎず、遅すぎない - 人間の知覚に最適化                   │
│   • 物理法則に従う - 自然で予測可能                            │
│   • 感情を伝える - 喜び、安心、期待                            │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 3.2 Spring Physics System (Enhanced)

```python
@dataclass
class SpringPresets:
    """Physics-based motion presets"""

    # === Bouncy - 弾むような動き（成功、喜び） ===
    bouncy = {
        "tension": 400,
        "friction": 15,
        "mass": 1.0,
        "use_case": "celebrations, success states"
    }

    # === Snappy - 俊敏な反応（ボタン、クイックアクション） ===
    snappy = {
        "tension": 600,
        "friction": 25,
        "mass": 0.8,
        "use_case": "button presses, quick feedback"
    }

    # === Smooth - 滑らかな遷移（ページ遷移、モーダル） ===
    smooth = {
        "tension": 200,
        "friction": 26,
        "mass": 1.2,
        "use_case": "page transitions, modal open/close"
    }

    # === Gentle - 優しい動き（背景、環境アニメーション） ===
    gentle = {
        "tension": 120,
        "friction": 20,
        "mass": 1.5,
        "use_case": "background animations, ambient motion"
    }

    # === Elastic - 弾性的な戻り（オーバーシュート効果） ===
    elastic = {
        "tension": 350,
        "friction": 12,
        "mass": 1.0,
        "use_case": "pull-to-refresh, overscroll"
    }
```

### 3.3 Gesture Response System

```python
class GestureAnimation:
    """Responsive gesture feedback"""

    # === タップ/クリック ===
    tap_scale_down: float = 0.95      # 押下時の縮小
    tap_scale_up: float = 1.02        # 離した瞬間の拡大
    tap_duration: int = 100           # ms

    # === ホバー ===
    hover_scale: float = 1.03         # ホバー時の拡大
    hover_glow_intensity: float = 0.3  # グロー強度
    hover_lift: int = 4               # 浮遊感（シャドウ）

    # === ドラッグ ===
    drag_scale: float = 1.05          # ドラッグ中の拡大
    drag_rotation_factor: float = 0.1  # ドラッグ方向への傾き

    # === ロングプレス ===
    long_press_scale: float = 0.92    # 長押し時の縮小
    long_press_vibrate: bool = True   # 触覚フィードバック
```

### 3.4 Transition Choreography

```python
class TransitionChoreography:
    """Orchestrated transitions"""

    # === Stagger Animation ===
    # リスト要素が順番にアニメーションする
    stagger_delay: int = 50           # 各要素間の遅延 (ms)
    stagger_max_items: int = 10       # 最大スタガー数

    # === Shared Element Transition ===
    # 画面間で共有される要素のシームレスな移動
    shared_element_duration: int = 400
    shared_element_easing: str = "spring(smooth)"

    # === Container Transform ===
    # FABやカードがモーダルに変形
    container_transform_duration: int = 350
    container_transform_fade_through: bool = True
```

---

## 4. Component Design

### 4.1 Hero Translation Area - "The Stage"

メインの翻訳エリア。ユーザーの視線が最初に向かう「舞台」。

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│                     ╭───────────────╮                       │
│                     │   Cosmic     │  ← Dynamic Island     │
│                     │   Glow       │    (Status Indicator)  │
│                     ╰───────────────╯                       │
│                                                             │
│         ┌─────────────────────────────────────┐             │
│         │                                     │             │
│         │     ┌───────────────────────┐       │             │
│         │     │                       │       │             │
│         │     │    📄                 │       │             │
│         │     │                       │       │             │
│         │     │  Drop PDF here        │       │ ← File Drop │
│         │     │  or click to browse   │       │   Area      │
│         │     │                       │       │             │
│         │     └───────────────────────┘       │             │
│         │                                     │             │
│         │     ════════════════════════        │             │
│         │           Particles ✨              │             │
│         │                                     │             │
│         └─────────────────────────────────────┘             │
│                      Hero Card                              │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 4.2 Dynamic Island 2.0 - "Living Status"

iPhone 14 の Dynamic Island を進化させた、生きているステータス表示。

```python
class DynamicIsland2:
    """
    Evolution of Dynamic Island - a living, breathing status indicator
    """

    # === States ===
    states = {
        "idle": {
            "width": 120,
            "height": 36,
            "shape": "pill",
            "animation": "subtle_breathing",
            "content": "minimal"
        },
        "active": {
            "width": 280,
            "height": 64,
            "shape": "rounded_rectangle",
            "animation": "pulsing_glow",
            "content": "progress + status"
        },
        "expanded": {
            "width": 360,
            "height": 120,
            "shape": "squircle",
            "animation": "aurora_flow",
            "content": "full_details"
        },
        "celebrating": {
            "width": 320,
            "height": 80,
            "shape": "organic_blob",
            "animation": "particle_burst + glow_pulse",
            "content": "success_message"
        }
    }

    # === Morphing Animation ===
    # 状態変化時、シェイプがスムーズに変形
    morph_duration: int = 400
    morph_spring: str = "smooth"

    # === Inner Content Animation ===
    # コンテンツは fade through でシームレスに切り替わる
    content_fade_duration: int = 200
```

### 4.3 File Drop Area 2.0 - "The Portal"

ファイルを「投げ込む」のではなく「世界に送り出す」感覚。

```python
class FileDropPortal:
    """
    File drop reimagined as a portal between languages
    """

    # === Visual Design ===
    design = {
        "background": "gradient(radial, center, transparent → bg_surface)",
        "border": "dashed, 2px, animated",
        "icon": "animated_document_morphing",
        "hover_effect": "portal_open_animation"
    }

    # === States ===
    states = {
        "idle": {
            "border_animation": "slow_dash_rotation",
            "icon_animation": "gentle_float",
            "glow": "none"
        },
        "hover": {
            "border_animation": "fast_pulse",
            "icon_animation": "excited_bounce",
            "glow": "outer_rim_cyan"
        },
        "drag_over": {
            "border_animation": "solid_glow",
            "icon_animation": "welcoming_expand",
            "glow": "full_portal_effect",
            "background": "animated_vortex"
        },
        "has_file": {
            "border_animation": "steady_glow",
            "icon_animation": "satisfied_rest",
            "glow": "success_accent"
        }
    }

    # === Drop Animation ===
    drop_animation = {
        "sequence": [
            ("scale", 1.0, 0.85, 100),      # Quick shrink
            ("particle_burst", "center", 30),  # Celebration
            ("scale", 0.85, 1.02, 200),      # Bounce back
            ("scale", 1.02, 1.0, 150),       # Settle
            ("glow_pulse", 2)                # Confirm
        ]
    }
```

### 4.4 Translation Mode Selector - "Language Bridge"

翻訳方向の選択を、視覚的に「橋」として表現。

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   ┌───────────┐     ══════════════     ┌───────────┐        │
│   │           │    ◀═══   ✦   ═══▶    │           │        │
│   │    JP     │    ══════════════     │    EN     │        │
│   │   日本語   │         Bridge        │  English  │        │
│   └───────────┘                        └───────────┘        │
│                                                             │
│   [============ Progress Bar ============]                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

```python
class LanguageBridge:
    """
    Visual representation of translation direction
    """

    # === Bridge Animation ===
    # 選択された方向に「流れ」が生まれる
    flow_animation = {
        "jp_to_en": {
            "particles": "left_to_right",
            "gradient": "gradient_flow_right",
            "active_side": "right"
        },
        "en_to_jp": {
            "particles": "right_to_left",
            "gradient": "gradient_flow_left",
            "active_side": "left"
        }
    }

    # === Selection Animation ===
    selection_animation = {
        "duration": 400,
        "spring": "bouncy",
        "effects": [
            "scale_bounce",
            "color_shift",
            "particle_trail"
        ]
    }
```

### 4.5 Action Button - "The Catalyst"

翻訳を開始する「触媒」ボタン。押すことで化学反応が起きる感覚。

```python
class CatalystButton:
    """
    The button that triggers the translation magic
    """

    # === Design ===
    design = {
        "shape": "squircle",
        "size": (220, 56),
        "background": "gradient(accent_primary → accent_secondary)",
        "text_style": "bold, 18px, white",
        "shadow": "glow_shadow"
    }

    # === States ===
    states = {
        "idle": {
            "background": "gradient",
            "glow": "subtle_outer_glow",
            "animation": "breathing_scale"
        },
        "hover": {
            "background": "brighter_gradient",
            "glow": "intense_outer_glow",
            "animation": "eager_pulse",
            "transform": "scale(1.03) translateY(-2px)"
        },
        "pressed": {
            "background": "darker_gradient",
            "glow": "inner_glow",
            "animation": "compress",
            "transform": "scale(0.95)"
        },
        "loading": {
            "background": "animated_gradient_flow",
            "glow": "rotating_glow",
            "animation": "circular_progress",
            "text": "dynamic_progress_text"
        },
        "disabled": {
            "background": "muted_solid",
            "glow": "none",
            "animation": "none",
            "opacity": 0.5
        }
    }

    # === Trigger Animation ===
    trigger_sequence = [
        ("haptic_feedback", "medium"),
        ("scale", 1.0, 0.9, 80),
        ("ripple_effect", "center_outward"),
        ("scale", 0.9, 1.05, 150),
        ("scale", 1.05, 1.0, 100),
        ("transition_to_loading")
    ]
```

### 4.6 Results Display - "The Revelation"

翻訳結果を「啓示」のように表示する、ドラマチックな結果表示。

```python
class ResultsRevelation:
    """
    Translation results revealed with dramatic flair
    """

    # === Entrance Animation ===
    entrance = {
        "type": "bottom_sheet_spring",
        "duration": 500,
        "spring": "smooth",
        "overlay": "fade_in_blur",
        "content_stagger": 80
    }

    # === Row Animation ===
    # 各翻訳ペアが順番にアニメーションで登場
    row_animation = {
        "initial": {"opacity": 0, "translateY": 20},
        "final": {"opacity": 1, "translateY": 0},
        "spring": "snappy",
        "delay_per_item": 50
    }

    # === Copy Feedback ===
    # コピー時の満足感のあるフィードバック
    copy_feedback = {
        "button_animation": "check_morph",
        "tooltip": "Copied!",
        "haptic": "success",
        "particle_burst": True
    }
```

---

## 5. Micro-interactions - "The Soul"

### 5.1 Philosophy

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   「神は細部に宿る」                                          │
│                                                             │
│   - マイクロインタラクションが「魂」を吹き込む                    │
│   - 1pxの動き、10msの遅延が体験を決定づける                     │
│   - ユーザーは気づかないが、確実に感じている                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 5.2 Micro-interaction Catalog

```python
class MicroInteractions:
    """Collection of micro-interactions that bring the UI to life"""

    # === Hover Glow ===
    hover_glow = {
        "trigger": "mouse_enter",
        "effect": "outer_glow_fade_in",
        "duration": 200,
        "color": "accent_primary_30_opacity"
    }

    # === Focus Ring ===
    focus_ring = {
        "trigger": "keyboard_focus",
        "effect": "animated_ring_pulse",
        "color": "accent_primary",
        "width": 2,
        "offset": 3
    }

    # === Button Press Ripple ===
    button_ripple = {
        "trigger": "click",
        "effect": "material_ripple",
        "origin": "click_position",
        "color": "white_20_opacity",
        "duration": 400
    }

    # === Toggle Switch ===
    toggle_animation = {
        "trigger": "state_change",
        "knob_animation": "spring_slide",
        "track_animation": "color_morph",
        "duration": 300,
        "spring": "snappy"
    }

    # === Input Focus ===
    input_focus = {
        "trigger": "focus",
        "border_animation": "color_transition",
        "label_animation": "float_up_shrink",
        "duration": 200
    }

    # === Success Checkmark ===
    success_checkmark = {
        "trigger": "success",
        "animation": "draw_checkmark",
        "duration": 400,
        "followed_by": "subtle_glow_pulse"
    }

    # === Error Shake ===
    error_shake = {
        "trigger": "error",
        "animation": "horizontal_shake",
        "intensity": 8,  # pixels
        "duration": 400,
        "followed_by": "red_glow_pulse"
    }

    # === Loading Dots ===
    loading_dots = {
        "trigger": "loading",
        "animation": "wave_bounce",
        "stagger": 150,
        "duration": 600,
        "loop": True
    }
```

### 5.3 Celebration System

```python
class CelebrationSystem:
    """Making success feel special"""

    # === Translation Complete ===
    translation_complete = {
        "particle_burst": {
            "count": 50,
            "colors": ["#00F5D4", "#7B61FF", "#FFFFFF"],
            "spread": 180,  # degrees
            "velocity": (8, 15),
            "gravity": 0.3,
            "lifetime": (1000, 2000)
        },
        "glow_pulse": {
            "color": "accent_primary",
            "intensity": 0.6,
            "duration": 800
        },
        "haptic": "success",
        "sound": "success_chime"
    }

    # === Large Job Complete ===
    large_job_complete = {
        "confetti": {
            "count": 100,
            "colors": "rainbow",
            "duration": 3000
        },
        "text_animation": "wave_celebration",
        "dynamic_island": "expand_celebration"
    }
```

---

## 6. Layout System

### 6.1 Window Structure

```
┌─────────────────────────────────────────────────────────────┐
│ Window: 540 x 900 (default) / Min: 500 x 750 / Max: 800 x 1200
├─────────────────────────────────────────────────────────────┤
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Background Layer                         │   │
│  │   - Aurora gradient animation                         │   │
│  │   - Ambient glow (responds to state)                  │   │
│  │   - Particle layer (celebration effects)              │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
│  ┌──────────────────────────────────────────────────────┐   │
│  │              Content Layer                            │   │
│  │                                                       │   │
│  │   ┌───────────────────────────────────────────┐      │   │
│  │   │         Dynamic Island (Status)           │      │   │
│  │   └───────────────────────────────────────────┘      │   │
│  │                    ↕ 24px                             │   │
│  │   ┌───────────────────────────────────────────┐      │   │
│  │   │                                           │      │   │
│  │   │          Hero Card (Main Area)            │      │   │
│  │   │                                           │      │   │
│  │   │   - File Drop Portal                      │      │   │
│  │   │   - Translation Progress                  │      │   │
│  │   │                                           │      │   │
│  │   └───────────────────────────────────────────┘      │   │
│  │                    ↕ 24px                             │   │
│  │   ┌───────────────────────────────────────────┐      │   │
│  │   │          Language Bridge                  │      │   │
│  │   └───────────────────────────────────────────┘      │   │
│  │                    ↕ 16px                             │   │
│  │   ┌───────────────────────────────────────────┐      │   │
│  │   │         Action Button (Catalyst)          │      │   │
│  │   └───────────────────────────────────────────┘      │   │
│  │                    ↕ 24px                             │   │
│  │   ┌───────────────────────────────────────────┐      │   │
│  │   │           Settings Panel                  │      │   │
│  │   └───────────────────────────────────────────┘      │   │
│  │                                                       │   │
│  └──────────────────────────────────────────────────────┘   │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 6.2 Responsive Behavior

```python
class ResponsiveLayout:
    """Adaptive layout for different window sizes"""

    breakpoints = {
        "compact": (0, 600),      # Small window
        "standard": (601, 900),   # Default
        "expanded": (901, 1200)   # Large window
    }

    layouts = {
        "compact": {
            "hero_card": {"height": "40%", "padding": 16},
            "dynamic_island": {"size": "small"},
            "action_button": {"width": "100%", "height": 48}
        },
        "standard": {
            "hero_card": {"height": "45%", "padding": 24},
            "dynamic_island": {"size": "medium"},
            "action_button": {"width": 220, "height": 56}
        },
        "expanded": {
            "hero_card": {"height": "50%", "padding": 32},
            "dynamic_island": {"size": "large"},
            "action_button": {"width": 280, "height": 64}
        }
    }
```

---

## 7. Sound Design - "Sonic Identity"

### 7.1 Sound Philosophy

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   「聞こえるか聞こえないかの境界」                              │
│                                                             │
│   - 音は装飾ではなく、情報の一部                               │
│   - 過度な音は雑音、適切な音は体験を完成させる                   │
│   - Apple Pay の「チーン」レベルの控えめさ                      │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 7.2 Sound Palette

```python
class SoundDesign:
    """Minimal, meaningful audio feedback"""

    sounds = {
        # === Translation Start ===
        "start": {
            "type": "tone",
            "frequency": 660,  # E5
            "duration": 40,
            "envelope": "quick_fade"
        },

        # === Success ===
        "success": {
            "type": "chord",
            "frequencies": [880, 1320],  # A5, E6 (perfect fifth)
            "duration": 150,
            "envelope": "soft_attack_long_decay",
            "description": "Apple Pay style double tone"
        },

        # === Progress Tick ===
        "progress_tick": {
            "type": "click",
            "frequency": 1000,
            "duration": 10,
            "volume": 0.3
        },

        # === Error ===
        "error": {
            "type": "tone",
            "frequency": 330,  # E4 (low)
            "duration": 200,
            "envelope": "soft"
        },

        # === Warning ===
        "warning": {
            "type": "tone",
            "frequency": 440,  # A4
            "duration": 100,
            "envelope": "soft"
        }
    }

    # === User Preference ===
    user_settings = {
        "sounds_enabled": True,
        "volume": 0.5,  # 0.0 - 1.0
        "success_sound_on_large_jobs_only": False
    }
```

---

## 8. Accessibility - "Universal Design"

### 8.1 Accessibility Principles

```
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│   「美しさは包括的でなければならない」                          │
│                                                             │
│   - M3 Expressive の研究: 年齢による使いやすさの差を解消        │
│   - アクセシビリティは制約ではなく、デザインの質を高める          │
│   - すべてのユーザーが同じ体験を得られる                        │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

### 8.2 Accessibility Features

```python
class AccessibilityFeatures:
    """Making beauty accessible to everyone"""

    # === Visual ===
    visual = {
        "high_contrast_mode": True,
        "reduced_motion_mode": True,
        "large_text_mode": True,
        "color_blind_safe_palette": True
    }

    # === Color Contrast ===
    # WCAG 2.1 AA 準拠 (最低 4.5:1)
    contrast_ratios = {
        "text_on_bg": 7.2,       # 目標 AAA
        "accent_on_bg": 5.1,     # AA 準拠
        "secondary_text": 4.5    # AA 最低限
    }

    # === Reduced Motion ===
    reduced_motion = {
        "spring_animations": "simplified_to_fade",
        "particle_effects": "disabled",
        "background_animations": "static",
        "transitions": "instant_or_fade"
    }

    # === Keyboard Navigation ===
    keyboard = {
        "focus_visible": True,
        "tab_order": "logical",
        "shortcuts": {
            "Ctrl+Enter": "start_translation",
            "Escape": "cancel",
            "Ctrl+C": "copy_results"
        }
    }

    # === Screen Reader ===
    screen_reader = {
        "aria_labels": True,
        "live_regions": True,
        "progress_announcements": True
    }
```

---

## 9. Performance Guidelines

### 9.1 Animation Performance

```python
class PerformanceGuidelines:
    """Keeping the UI silky smooth"""

    # === Target Frame Rate ===
    target_fps: int = 60
    frame_budget_ms: float = 16.67  # 1000ms / 60fps

    # === Animation Optimization ===
    animation_rules = {
        "prefer_transform_and_opacity": True,  # GPU accelerated
        "avoid_layout_thrashing": True,
        "batch_dom_updates": True,
        "use_will_change_sparingly": True
    }

    # === Particle System Limits ===
    particle_limits = {
        "max_active_particles": 200,
        "cleanup_interval_ms": 100,
        "auto_reduce_on_low_fps": True
    }

    # === Lazy Loading ===
    lazy_loading = {
        "defer_non_critical_animations": True,
        "preload_celebration_assets": True,
        "unload_invisible_components": True
    }
```

---

## 10. Implementation Roadmap

### Phase 1: Foundation (Week 1-2)
- [ ] New color system implementation
- [ ] Typography system update
- [ ] Enhanced spacing system
- [ ] Basic spring animation improvements

### Phase 2: Core Components (Week 3-4)
- [ ] Dynamic Island 2.0
- [ ] File Drop Portal
- [ ] Language Bridge
- [ ] Catalyst Button

### Phase 3: Polish (Week 5-6)
- [ ] Micro-interactions library
- [ ] Celebration system
- [ ] Sound design integration
- [ ] Accessibility features

### Phase 4: Optimization (Week 7-8)
- [ ] Performance optimization
- [ ] Reduced motion mode
- [ ] Cross-platform testing
- [ ] Final polish

---

## 11. Design References

### Inspiration Sources
- [Material Design 3 Expressive](https://m3.material.io/blog/building-with-m3-expressive)
- [LocaLingo Translation App](https://github.com/soukouki/LocaLingo)
- Apple Human Interface Guidelines
- iOS Dynamic Island interaction patterns

### Research Backing
- Google's 46 research studies with 18,000+ participants
- M3 Expressive: Reduced age effects in UI usability
- Strategic use of color, size, shape for faster navigation

---

## 12. Success Metrics

### User Experience KPIs
| Metric | Current | Target |
|--------|---------|--------|
| First impression score | - | 9/10 |
| Task completion time | - | < 5s |
| Error rate | - | < 1% |
| User satisfaction (NPS) | - | > 70 |

### Technical KPIs
| Metric | Target |
|--------|--------|
| Animation FPS | 60fps |
| First contentful paint | < 500ms |
| Input latency | < 50ms |
| Memory usage | < 200MB |

---

> **Conclusion**: このUI仕様書は、翻訳アプリを「世界をとる」レベルに引き上げるための設計図です。
> Apple の洗練さと M3 Expressive の感情的なデザインを融合し、
> ユーザーが翻訳するたびに小さな感動を覚える体験を創造します。
>
> 「美しさは機能である」- この信念のもと、すべてのピクセル、すべてのミリ秒に意味を持たせます。
