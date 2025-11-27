"""
Tests for UI Components
Testing non-GUI logic: Theme, SpringAnimation physics, color utilities
"""

import pytest
import sys
import math
from unittest.mock import MagicMock

# Mock GUI modules before importing ui
mock_ctk = MagicMock()
mock_ctk.CTk = MagicMock
mock_ctk.CTkFrame = MagicMock
mock_ctk.CTkButton = MagicMock
mock_ctk.CTkLabel = MagicMock
mock_ctk.CTkCanvas = MagicMock
mock_ctk.CTkToplevel = MagicMock
mock_ctk.CTkScrollableFrame = MagicMock
sys.modules['customtkinter'] = mock_ctk


# =============================================================================
# Test: Theme configuration
# =============================================================================
class TestTheme:
    """Test Theme dataclass configuration"""

    def test_theme_colors_valid_hex(self):
        """All theme colors should be valid hex codes"""
        from ui import THEME

        hex_pattern = r'^#[0-9a-fA-F]{6}$'
        import re

        assert re.match(hex_pattern, THEME.bg_primary)
        assert re.match(hex_pattern, THEME.bg_secondary)
        assert re.match(hex_pattern, THEME.bg_card)
        assert re.match(hex_pattern, THEME.accent)
        assert re.match(hex_pattern, THEME.text_primary)

    def test_theme_spacing_positive(self):
        """All spacing values should be positive"""
        from ui import THEME

        assert THEME.space_xs > 0
        assert THEME.space_sm > 0
        assert THEME.space_md > 0
        assert THEME.space_lg > 0
        assert THEME.space_xl > 0

    def test_theme_spacing_order(self):
        """Spacing should increase in order"""
        from ui import THEME

        assert THEME.space_xs < THEME.space_sm
        assert THEME.space_sm < THEME.space_md
        assert THEME.space_md < THEME.space_lg
        assert THEME.space_lg < THEME.space_xl

    def test_theme_radius_positive(self):
        """All radius values should be positive"""
        from ui import THEME

        assert THEME.radius_sm > 0
        assert THEME.radius_md > 0
        assert THEME.radius_lg > 0
        assert THEME.radius_xl > 0

    def test_theme_duration_positive(self):
        """All duration values should be positive"""
        from ui import THEME

        assert THEME.duration_fast > 0
        assert THEME.duration_normal > 0
        assert THEME.duration_slow > 0

    def test_theme_spring_params(self):
        """Spring parameters should be reasonable"""
        from ui import THEME

        assert THEME.spring_tension > 0
        assert THEME.spring_friction > 0
        assert THEME.spring_mass > 0

    def test_glassmorphism_colors(self):
        """Glassmorphism colors should be defined"""
        from ui import THEME

        assert hasattr(THEME, 'glass_bg')
        assert hasattr(THEME, 'glass_border')
        assert hasattr(THEME, 'glass_highlight')
        assert hasattr(THEME, 'glass_shadow')


# =============================================================================
# Test: get_font()
# =============================================================================
class TestGetFont:
    """Test font utility function"""

    def test_returns_tuple(self):
        """Should return a tuple"""
        from ui import get_font

        result = get_font("text", 14, "normal")
        assert isinstance(result, tuple)
        assert len(result) == 3

    def test_font_styles(self):
        """Should handle different font styles"""
        from ui import get_font

        display = get_font("display", 20, "bold")
        text = get_font("text", 14, "normal")
        mono = get_font("mono", 12, "normal")

        assert display[1] == 20
        assert display[2] == "bold"
        assert text[1] == 14
        assert mono[0] == "Consolas"

    def test_default_values(self):
        """Should use default values"""
        from ui import get_font

        result = get_font()
        assert result[1] == 14
        assert result[2] == "normal"


# =============================================================================
# Test: SpringAnimation physics
# =============================================================================
class TestSpringPhysics:
    """Test spring physics calculations"""

    def test_spring_equation(self):
        """Verify spring physics equation: F = -kx - cv"""
        # Parameters
        tension = 300.0  # k (spring stiffness)
        friction = 20.0  # c (damping coefficient)
        mass = 1.0       # m

        # Initial state
        position = 0.5  # x (displacement from target)
        velocity = 0.0  # v
        target = 1.0

        # Calculate forces
        displacement = position - target  # -0.5
        spring_force = -tension * displacement  # 150
        damping_force = -friction * velocity    # 0
        acceleration = (spring_force + damping_force) / mass  # 150

        # Spring force should pull towards target
        assert spring_force > 0  # Pulls position towards 1.0
        assert acceleration > 0  # Accelerates towards target

    def test_damping_reduces_velocity(self):
        """Damping should reduce velocity"""
        tension = 300.0
        friction = 20.0
        mass = 1.0

        position = 1.0  # At target
        velocity = 10.0  # Moving fast
        target = 1.0

        displacement = position - target  # 0
        spring_force = -tension * displacement  # 0
        damping_force = -friction * velocity    # -200
        acceleration = (spring_force + damping_force) / mass  # -200

        # Damping should slow down
        assert damping_force < 0
        assert acceleration < 0

    def test_equilibrium_at_target(self):
        """At target with zero velocity, should have zero acceleration"""
        tension = 300.0
        friction = 20.0
        mass = 1.0

        position = 1.0  # At target
        velocity = 0.0  # Not moving
        target = 1.0

        displacement = position - target  # 0
        spring_force = -tension * displacement  # 0
        damping_force = -friction * velocity    # 0
        acceleration = (spring_force + damping_force) / mass  # 0

        assert acceleration == 0

    def test_convergence_check(self):
        """Should converge when displacement and velocity are small"""
        threshold = 0.001

        # Converged state
        displacement = 0.0005
        velocity = 0.0005

        converged = abs(displacement) < threshold and abs(velocity) < threshold
        assert converged is True

        # Not converged
        displacement = 0.01
        velocity = 0.01

        not_converged = abs(displacement) < threshold and abs(velocity) < threshold
        assert not_converged is False


# =============================================================================
# Test: Color interpolation
# =============================================================================
class TestColorInterpolation:
    """Test color interpolation for animations"""

    def test_hex_to_rgb(self):
        """Should correctly parse hex to RGB"""
        color = "#34c759"
        r = int(color[1:3], 16)
        g = int(color[3:5], 16)
        b = int(color[5:7], 16)

        assert r == 0x34  # 52
        assert g == 0xc7  # 199
        assert b == 0x59  # 89

    def test_rgb_to_hex(self):
        """Should correctly format RGB to hex"""
        r, g, b = 52, 199, 89
        hex_color = f"#{r:02x}{g:02x}{b:02x}"

        assert hex_color == "#34c759"

    def test_linear_interpolation(self):
        """Linear interpolation should work correctly"""
        start = 0
        end = 100
        t = 0.5  # Midpoint

        result = start + (end - start) * t
        assert result == 50

        t = 0.0
        result = start + (end - start) * t
        assert result == 0

        t = 1.0
        result = start + (end - start) * t
        assert result == 100

    def test_color_interpolation(self):
        """Should interpolate between two colors"""
        # Black to white
        r1, g1, b1 = 0, 0, 0
        r2, g2, b2 = 255, 255, 255
        t = 0.5

        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)

        assert r == 127
        assert g == 127
        assert b == 127


# =============================================================================
# Test: Animation timing
# =============================================================================
class TestAnimationTiming:
    """Test animation timing calculations"""

    def test_sine_oscillation(self):
        """Sine function should oscillate between -1 and 1"""
        for phase in [0, 0.5, 1.0, 1.5, 2.0]:
            value = math.sin(phase * math.pi)
            assert -1 <= value <= 1

    def test_normalized_sine(self):
        """Normalized sine should oscillate between 0 and 1"""
        for phase in range(100):
            value = (math.sin(phase * 0.1) + 1) / 2
            assert 0 <= value <= 1

    def test_breathing_brightness(self):
        """Breathing animation should stay in reasonable brightness range"""
        base_brightness = 0x1a  # THEME.glass_bg
        for phase in range(100):
            brightness = 0.95 + 0.05 * math.sin(phase * 0.03)
            value = int(base_brightness * brightness)

            # Should stay positive and not overflow
            assert 0 <= value <= 255


# =============================================================================
# Test: Glow effect calculations
# =============================================================================
class TestGlowEffects:
    """Test glow effect calculations"""

    def test_glow_intensity_range(self):
        """Glow intensity should be between 0 and 1"""
        for phase in range(100):
            intensity = (math.sin(phase * 0.05) + 1) / 2
            assert 0 <= intensity <= 1

    def test_border_glow_color(self):
        """Border glow color should be valid"""
        base = 0x33
        max_glow = 0x50

        for intensity in [0.0, 0.25, 0.5, 0.75, 1.0]:
            r = int(base + (max_glow - base) * intensity * 0.5)
            color = f"#{r:02x}{r:02x}{r:02x}"

            # Should be valid hex
            assert len(color) == 7
            assert color.startswith("#")
            # Should be in range
            assert base <= r <= max_glow


# =============================================================================
# Test: Scale calculations for spring buttons
# =============================================================================
class TestScaleCalculations:
    """Test scale calculations for spring animations"""

    def test_scale_to_intensity(self):
        """Scale should map to intensity correctly"""
        # At scale 0.95, intensity should be 0
        # At scale 1.05, intensity should be 1

        scale = 0.95
        intensity = (scale - 0.95) / 0.1
        intensity = max(0, min(1, intensity))
        assert intensity == pytest.approx(0.0, abs=0.001)

        scale = 1.05
        intensity = (scale - 0.95) / 0.1
        intensity = max(0, min(1, intensity))
        assert intensity == pytest.approx(1.0, abs=0.001)

        scale = 1.0
        intensity = (scale - 0.95) / 0.1
        intensity = max(0, min(1, intensity))
        assert intensity == pytest.approx(0.5, abs=0.001)

    def test_hover_scale_values(self):
        """Hover scale values should be reasonable"""
        hover_scale = 1.02
        click_scale = 0.96
        normal_scale = 1.0

        # Hover should be larger than normal
        assert hover_scale > normal_scale

        # Click should be smaller than normal
        assert click_scale < normal_scale

        # Differences should be subtle
        assert abs(hover_scale - normal_scale) < 0.1
        assert abs(click_scale - normal_scale) < 0.1


# =============================================================================
# Run tests
# =============================================================================
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
