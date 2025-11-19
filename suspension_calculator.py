import numpy as np
import matplotlib.pyplot as plt
from mpl_toolkits.mplot3d import Axes3D
from matplotlib.patches import Ellipse, Circle
import matplotlib.patches as mpatches
from scipy.interpolate import splprep, splev
import os
import time
import argparse
import sys

# ========== CONSTANTS ==========
# Hall/Gallery dimensions (defines the cube)
# Origin at left corner (0,0,0)
# X axis: going right (to back wall)
# Y axis: going into the scene (to lateral wall)
# Z axis: going up (height)
HALL_X_MAX = 9.0   # meters - back wall at x=9.0
HALL_Y_MAX = 6.0   # meters - lateral wall at y=6.0
HALL_Z_MAX = 4.5   # meters - ceiling at z=4.5

# ========== OUTPUT DIRECTORY SETUP ==========
def create_output_directory(project_name):
    """Create output directory with project name and timestamp."""
    timestamp = int(time.time())
    output_dir = f"data/results/{project_name}_{timestamp}"
    os.makedirs(output_dir, exist_ok=True)
    return output_dir

# ========== FUNCTIONS ==========

def detect_face(x, y, z, tolerance=1e-6):
    """
    Automatically detect which cube face a point lies on based on its coordinates.
    
    Coordinate system:
    - Origin at left corner (0,0,0)
    - X axis: going right (to back wall)
    - Y axis: going into scene (to lateral wall)
    - Z axis: going up (height)
    
    Parameters:
    -----------
    x, y, z : float
        Point coordinates
    tolerance : float
        Tolerance for face detection
    
    Returns:
    --------
    face_name : str
        Name of the detected face
    
    Raises:
    -------
    ValueError : If point is not on any face or is out of bounds
    """
    # Check floor (z = 0)
    if abs(z - 0) < tolerance:
        if 0 <= x <= HALL_X_MAX and 0 <= y <= HALL_Y_MAX:
            return 'floor'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at z=0 but outside floor bounds")
    
    # Check ceiling (z = HALL_Z_MAX)
    if abs(z - HALL_Z_MAX) < tolerance:
        if 0 <= x <= HALL_X_MAX and 0 <= y <= HALL_Y_MAX:
            return 'ceiling'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at z={HALL_Z_MAX} but outside ceiling bounds")
    
    # Check wall x=0 (left wall)
    if abs(x - 0) < tolerance:
        if 0 <= y <= HALL_Y_MAX and 0 <= z <= HALL_Z_MAX:
            return 'wall_x0'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at x=0 but outside wall bounds")
    
    # Check wall x=HALL_X_MAX (back wall, right side)
    if abs(x - HALL_X_MAX) < tolerance:
        if 0 <= y <= HALL_Y_MAX and 0 <= z <= HALL_Z_MAX:
            return 'wall_x_max'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at x={HALL_X_MAX} but outside wall bounds")
    
    # Check wall y=0 (front wall)
    if abs(y - 0) < tolerance:
        if 0 <= x <= HALL_X_MAX and 0 <= z <= HALL_Z_MAX:
            return 'wall_y0'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at y=0 but outside wall bounds")
    
    # Check wall y=HALL_Y_MAX (lateral wall, into scene)
    if abs(y - HALL_Y_MAX) < tolerance:
        if 0 <= x <= HALL_X_MAX and 0 <= z <= HALL_Z_MAX:
            return 'wall_y_max'
        else:
            raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is at y={HALL_Y_MAX} but outside wall bounds")
    
    # Point is not on any face
    raise ValueError(f"Point ({x:.3f}, {y:.3f}, {z:.3f}) is not on any cube face.\n"
                    f"Valid faces are:\n"
                    f"  floor: z=0\n"
                    f"  ceiling: z={HALL_Z_MAX}\n"
                    f"  wall_x0 (left): x=0\n"
                    f"  wall_x_max (back/right): x={HALL_X_MAX}\n"
                    f"  wall_y0 (front): y=0\n"
                    f"  wall_y_max (lateral/into scene): y={HALL_Y_MAX}")


def get_face_normal(face_name):
    """
    Get the outward normal vector for a cube face.
    
    Parameters:
    -----------
    face_name : str
        Name of the face
    
    Returns:
    --------
    normal : ndarray
        Unit normal vector pointing outward from the face
    """
    normals = {
        'floor': np.array([0, 0, -1]),
        'ceiling': np.array([0, 0, 1]),
        'wall_x0': np.array([-1, 0, 0]),      # left wall
        'wall_x_max': np.array([1, 0, 0]),    # back wall (right)
        'wall_y0': np.array([0, -1, 0]),      # front wall
        'wall_y_max': np.array([0, 1, 0])     # lateral wall (into scene)
    }
    return normals[face_name]


def should_mirror_template(face_name):
    """
    Determine if a template needs mirroring when printed and attached 
    from inside the cube.
    
    When you're inside the cube looking at a face, certain faces need 
    their coordinates mirrored so the template matches your perspective.
    
    Parameters:
    -----------
    face_name : str
        Name of the face
    
    Returns:
    --------
    mirror_horizontal : bool
        True if horizontal axis should be mirrored
    mirror_vertical : bool
        True if vertical axis should be mirrored
    
    Mirroring Logic:
    ----------------
    - floor: Looking DOWN - natural view, no mirroring needed
    - ceiling: Looking UP at underside - mirror vertical axis (Y)
    - wall_x0 (left): Looking RIGHT - natural view, no mirroring
    - wall_x_max (back): Looking LEFT (toward origin) - mirror horizontal (Y)
    - wall_y0 (front): Looking FORWARD - natural view, no mirroring
    - wall_y_max (lateral): Looking BACK (toward origin) - mirror horizontal (X)
    """
    mirror_rules = {
        'floor': (False, False),      # Looking down - natural view
        'ceiling': (False, True),     # Looking up - mirror Y axis
        'wall_x0': (False, False),    # Looking right - natural
        'wall_x_max': (True, False),  # Looking left - mirror horizontal (Y)
        'wall_y0': (False, False),    # Looking forward - natural
        'wall_y_max': (True, False)   # Looking back - mirror horizontal (X)
    }
    return mirror_rules.get(face_name, (False, False))


def apply_template_mirroring(points_2d, face_name):
    """
    Mirror template coordinates for physical installation from inside cube.
    
    This ensures that when you print the template and hold it against the 
    surface from inside, the coordinates match your physical perspective.
    
    Parameters:
    -----------
    points_2d : ndarray, shape (n, 2)
        2D points in face coordinates
    face_name : str
        Which face these points belong to
    
    Returns:
    --------
    mirrored_points : ndarray, shape (n, 2)
        Points with mirroring applied
    """
    mirror_h, mirror_v = should_mirror_template(face_name)
    
    mirrored_points = points_2d.copy()
    
    if mirror_h:
        mirrored_points[:, 0] = -mirrored_points[:, 0]
    
    if mirror_v:
        mirrored_points[:, 1] = -mirrored_points[:, 1]
    
    return mirrored_points


def get_mirroring_note(face_name):
    """
    Get a descriptive note about mirroring for the template.
    
    Parameters:
    -----------
    face_name : str
        Name of the face
    
    Returns:
    --------
    note : str
        Description of mirroring applied
    """
    mirror_h, mirror_v = should_mirror_template(face_name)
    
    if not mirror_h and not mirror_v:
        return "No mirroring applied - natural viewing perspective"
    
    notes = []
    if mirror_h:
        notes.append("Horizontal axis MIRRORED")
    if mirror_v:
        notes.append("Vertical axis MIRRORED")
    
    return " | ".join(notes) + " - for inside-cube installation"


def cartesian_to_polar(points, center):
    """
    Convert Cartesian coordinates to polar coordinates relative to a center.
    """
    center = np.array(center)
    n_points = len(points)
    polar_coords = np.zeros((n_points, 2))
    
    for i in range(n_points):
        dx = points[i, 0] - center[0]
        dy = points[i, 1] - center[1]
        
        r = np.sqrt(dx**2 + dy**2)
        theta = np.arctan2(dy, dx) * 180 / np.pi  # Convert to degrees
        
        # Ensure theta is in [0, 360)
        if theta < 0:
            theta += 360
            
        polar_coords[i] = [r, theta]
    
    return polar_coords


def calculate_cylinder_centers(start_point, end_point, bottom_position, drum_depth):
    """
    Calculate the bottom and top centers of the cylinder based on parametric position.
    
    Parameters:
    -----------
    start_point : array-like, shape (3,)
        Starting point of the axis
    end_point : array-like, shape (3,)
        Ending point of the axis
    bottom_position : float
        Position along axis for bottom rim (0 to 1)
    drum_depth : float
        Depth/height of the drum
    
    Returns:
    --------
    bottom_center : ndarray
        Center of bottom rim
    top_center : ndarray
        Center of top rim
    """
    start_point = np.array(start_point)
    end_point = np.array(end_point)
    
    # Calculate the axis direction
    axis = end_point - start_point
    axis_length = np.linalg.norm(axis)
    axis_unit = axis / axis_length
    
    # Bottom center at parametric position
    bottom_center = start_point + bottom_position * axis
    
    # Top center is drum_depth away from bottom along axis
    top_center = bottom_center + drum_depth * axis_unit
    
    return bottom_center, top_center


def calculate_cylinder_attachment_points(bottom_center, top_center, radius, num_points):
    """
    Calculate attachment points for a tilted cylinder (drum) suspended in a hall.
    """
    
    bottom_center = np.array(bottom_center)
    top_center = np.array(top_center)
    
    # Calculate cylinder axis (unit vector)
    axis = top_center - bottom_center
    axis_length = np.linalg.norm(axis)
    axis_unit = axis / axis_length
    
    # Create perpendicular vectors to form local coordinate system
    # Find a vector not parallel to axis
    if abs(axis_unit[0]) < 0.9:
        arbitrary = np.array([1, 0, 0])
    else:
        arbitrary = np.array([0, 1, 0])
    
    # Create two perpendicular vectors in the plane perpendicular to axis
    perp1 = np.cross(axis_unit, arbitrary)
    perp1 = perp1 / np.linalg.norm(perp1)
    
    perp2 = np.cross(axis_unit, perp1)
    perp2 = perp2 / np.linalg.norm(perp2)
    
    # Generate angles for equidistant points (like drum lugs)
    angles = np.linspace(0, 2*np.pi, num_points, endpoint=False)
    
    # Calculate points on bottom circle
    bottom_points = np.zeros((num_points, 3))
    for i, angle in enumerate(angles):
        # Point on circle in local coordinates
        offset = radius * (np.cos(angle) * perp1 + np.sin(angle) * perp2)
        bottom_points[i] = bottom_center + offset
    
    # Calculate points on top circle
    top_points = np.zeros((num_points, 3))
    for i, angle in enumerate(angles):
        # Point on circle in local coordinates
        offset = radius * (np.cos(angle) * perp1 + np.sin(angle) * perp2)
        top_points[i] = top_center + offset
    
    return bottom_points, top_points, perp1, perp2, axis_unit


def find_plane_intersection(point, direction, face_name):
    """
    Find where a line from a point in a direction intersects a cube face.
    
    Parameters:
    -----------
    point : ndarray
        Starting point
    direction : ndarray
        Direction vector
    face_name : str
        Which face to intersect
    
    Returns:
    --------
    intersection : ndarray or None
        Intersection point, or None if no intersection
    """
    # Parametric line: P = point + t * direction
    # We need to find t where the line intersects the plane
    
    tolerance = 1e-6
    
    if face_name == 'floor':
        # z = 0
        if abs(direction[2]) < 1e-10:
            return None
        t = (0 - point[2]) / direction[2]
        
    elif face_name == 'ceiling':
        # z = HALL_Z_MAX
        if abs(direction[2]) < 1e-10:
            return None
        t = (HALL_Z_MAX - point[2]) / direction[2]
        
    elif face_name == 'wall_x0':
        # x = 0
        if abs(direction[0]) < 1e-10:
            return None
        t = (0 - point[0]) / direction[0]
        
    elif face_name == 'wall_x_max':
        # x = HALL_X_MAX
        if abs(direction[0]) < 1e-10:
            return None
        t = (HALL_X_MAX - point[0]) / direction[0]
        
    elif face_name == 'wall_y0':
        # y = 0
        if abs(direction[1]) < 1e-10:
            return None
        t = (0 - point[1]) / direction[1]
        
    elif face_name == 'wall_y_max':
        # y = HALL_Y_MAX
        if abs(direction[1]) < 1e-10:
            return None
        t = (HALL_Y_MAX - point[1]) / direction[1]
    else:
        return None
    
    intersection = point + t * direction
    
    # Check if intersection is within face bounds (with tolerance)
    try:
        detected_face = detect_face(intersection[0], intersection[1], intersection[2])
        if detected_face == face_name:
            return intersection
        else:
            return None
    except ValueError:
        return None


def generate_smooth_ellipse_curve(anchor_points, num_points=500):
    """
    Generate a smooth ellipse/circle curve through the anchor points using spline interpolation.
    Handles cases with invalid (nan) points.
    """
    # Filter out any nan points
    valid_mask = ~np.isnan(anchor_points).any(axis=1)
    valid_points = anchor_points[valid_mask]
    
    if len(valid_points) < 3:
        raise ValueError(f"Need at least 3 valid points for curve generation, got {len(valid_points)}")
    
    # Extract XY coordinates (for 2D projection on face)
    if valid_points.shape[1] == 3:
        xy_points = valid_points[:, :2]
    else:
        xy_points = valid_points
    
    # Close the loop by adding the first point at the end
    xy_closed = np.vstack([xy_points, xy_points[0]])
    
    # Use parametric spline interpolation for a smooth closed curve
    tck, u = splprep([xy_closed[:, 0], xy_closed[:, 1]], s=0, per=True)
    
    # Evaluate the spline at many points for a smooth curve
    u_new = np.linspace(0, 1, num_points)
    x_smooth, y_smooth = splev(u_new, tck)
    
    curve_points = np.column_stack([x_smooth, y_smooth])
    
    return curve_points


def generate_cylinder_surface(bottom_center, top_center, radius, perp1, perp2, num_circumference=50, num_height=20):
    """
    Generate points on the cylinder surface for visualization.
    """
    # Angles around the circumference
    theta = np.linspace(0, 2*np.pi, num_circumference)
    # Height parameter (0 = bottom, 1 = top)
    h = np.linspace(0, 1, num_height)
    
    # Create meshgrid
    THETA, H = np.meshgrid(theta, h)
    
    # Initialize surface arrays
    X = np.zeros_like(THETA)
    Y = np.zeros_like(THETA)
    Z = np.zeros_like(THETA)
    
    # Calculate surface points
    for i in range(num_height):
        for j in range(num_circumference):
            # Interpolate center along cylinder axis
            center = bottom_center + H[i, j] * (top_center - bottom_center)
            # Calculate point on circumference
            offset = radius * (np.cos(THETA[i, j]) * perp1 + np.sin(THETA[i, j]) * perp2)
            point = center + offset
            X[i, j] = point[0]
            Y[i, j] = point[1]
            Z[i, j] = point[2]
    
    return X, Y, Z


def project_to_2d(points_3d, face_name):
    """
    Project 3D points onto 2D coordinates for a specific face.
    
    Coordinate system: X right, Y into scene, Z up
    
    Parameters:
    -----------
    points_3d : ndarray, shape (n, 3)
        3D points (X, Y, Z)
    face_name : str
        Which face to project onto
    
    Returns:
    --------
    points_2d : ndarray, shape (n, 2)
        2D coordinates on the face
    axis_labels : tuple
        Labels for the 2D axes
    """
    if face_name in ['floor', 'ceiling']:
        # Use X (horizontal right), Y (into scene)
        return points_3d[:, :2], ('X', 'Y')
    elif face_name in ['wall_x0', 'wall_x_max']:
        # Use Y (horizontal, into scene), Z (vertical, up)
        return points_3d[:, 1:3], ('Y', 'Z')
    elif face_name in ['wall_y0', 'wall_y_max']:
        # Use X (horizontal, right), Z (vertical, up)
        return points_3d[:, [0, 2]], ('X', 'Z')


def get_face_center_2d(face_name):
    """Get the 2D center point for a face."""
    if face_name in ['floor', 'ceiling']:
        return np.array([HALL_X_MAX/2, HALL_Y_MAX/2])
    elif face_name in ['wall_x0', 'wall_x_max']:
        return np.array([HALL_Y_MAX/2, HALL_Z_MAX/2])
    elif face_name in ['wall_y0', 'wall_y_max']:
        return np.array([HALL_X_MAX/2, HALL_Z_MAX/2])


def plot_template(start_face_points, end_face_points, start_face_name, end_face_name, 
                  start_point_3d, end_point_3d, bottom_center, top_center, radius, perp1, perp2, axis_unit,
                  output_dir):
    """
    Create printable templates showing the anchor points for drilling on two faces.
    Templates are mirrored for inside-cube installation perspective.
    """
    
    # Check for nan values
    start_valid = ~np.isnan(start_face_points).any(axis=1)
    end_valid = ~np.isnan(end_face_points).any(axis=1)
    
    if not start_valid.all():
        print(f"\nWARNING: {(~start_valid).sum()} anchor points on {start_face_name} are outside bounds and will be skipped")
    if not end_valid.all():
        print(f"WARNING: {(~end_valid).sum()} anchor points on {end_face_name} are outside bounds and will be skipped")
    
    # Get axis point projections on each face
    start_2d, start_labels = project_to_2d(np.array([start_point_3d]), start_face_name)
    end_2d, end_labels = project_to_2d(np.array([end_point_3d]), end_face_name)
    
    start_axis_point = start_2d[0]
    end_axis_point = end_2d[0]
    
    # Get face centers
    start_face_center = get_face_center_2d(start_face_name)
    end_face_center = get_face_center_2d(end_face_name)
    
    # Project anchor points to 2D (filter out nans)
    start_points_valid = start_face_points[start_valid]
    end_points_valid = end_face_points[end_valid]
    
    start_points_2d, _ = project_to_2d(start_points_valid, start_face_name)
    end_points_2d, _ = project_to_2d(end_points_valid, end_face_name)
    
    # Convert to relative coordinates
    start_points_relative = start_points_2d - start_axis_point
    end_points_relative = end_points_2d - end_axis_point
    
    # *** APPLY MIRRORING FOR INSIDE-CUBE INSTALLATION ***
    start_points_relative = apply_template_mirroring(start_points_relative, start_face_name)
    end_points_relative = apply_template_mirroring(end_points_relative, end_face_name)
    
    # Get mirroring notes
    start_mirror_note = get_mirroring_note(start_face_name)
    end_mirror_note = get_mirroring_note(end_face_name)
    
    # Generate smooth curves (also need mirroring)
    try:
        start_curve_3d = generate_smooth_ellipse_curve(start_face_points, num_points=500)
        start_curve_2d = start_curve_3d
        start_curve_relative = start_curve_2d - start_axis_point
        start_curve_relative = apply_template_mirroring(start_curve_relative, start_face_name)
    except ValueError as e:
        print(f"Warning: Could not generate curve for {start_face_name}: {e}")
        start_curve_relative = None
    
    try:
        end_curve_3d = generate_smooth_ellipse_curve(end_face_points, num_points=500)
        end_curve_2d = end_curve_3d
        end_curve_relative = end_curve_2d - end_axis_point
        end_curve_relative = apply_template_mirroring(end_curve_relative, end_face_name)
    except ValueError as e:
        print(f"Warning: Could not generate curve for {end_face_name}: {e}")
        end_curve_relative = None
    
    # Calculate maximum extents
    max_dist_start = np.max(np.abs(start_points_relative)) + 0.3
    max_dist_end = np.max(np.abs(end_points_relative)) + 0.3
    max_dist = max(max_dist_start, max_dist_end)
    
    # Calculate figure size for 1:1 scale
    meters_to_inches = 39.3701
    fig_width = 2 * max_dist * meters_to_inches
    fig_height = 2 * max_dist * meters_to_inches
    
    print(f"\nTemplate dimensions:")
    print(f"  Plot area: {2*max_dist:.3f} m × {2*max_dist:.3f} m")
    print(f"  Figure size: {fig_width:.1f} × {fig_height:.1f} inches")
    
    # ===== START FACE TEMPLATE =====
    fig1 = plt.figure(figsize=(fig_width, fig_height))
    ax1 = fig1.add_subplot(111)
    
    if start_curve_relative is not None:
        ax1.plot(start_curve_relative[:, 0], start_curve_relative[:, 1], 
                 'b:', linewidth=3, alpha=0.7, label='Intersection curve', zorder=4)
    
    ax1.scatter(start_points_relative[:, 0], start_points_relative[:, 1], c='red', s=300, 
               marker='+', linewidths=4, zorder=6, label='Anchor points')
    
    valid_idx = 0
    for i in range(len(start_face_points)):
        if start_valid[i]:
            coord_text = f'{i+1}\n({start_points_relative[valid_idx, 0]:.3f}, {start_points_relative[valid_idx, 1]:.3f})'
            ax1.text(start_points_relative[valid_idx, 0] + 0.03, start_points_relative[valid_idx, 1] + 0.03, coord_text, 
                    fontsize=11, fontweight='bold', color='black',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8))
            valid_idx += 1
    
    ax1.scatter(0, 0, c='blue', s=500, marker='x', linewidths=6, zorder=5, label='CENTER (Origin)')
    ax1.text(0.05, 0.05, 'ORIGIN\n(0, 0)', fontsize=14, fontweight='bold', color='blue')
    
    for i in range(len(start_points_relative)):
        ax1.plot([0, start_points_relative[i, 0]], [0, start_points_relative[i, 1]], 
                'gray', linestyle=':', linewidth=1.5, alpha=0.5, zorder=3)
    
    ax1.set_xlim(-max_dist, max_dist)
    ax1.set_ylim(-max_dist, max_dist)
    ax1.axhline(y=0, color='black', linewidth=2, alpha=0.8)
    ax1.axvline(x=0, color='black', linewidth=2, alpha=0.8)
    ax1.grid(True, alpha=0.5, linestyle='-', linewidth=0.8, which='both')
    ax1.minorticks_on()
    ax1.grid(True, which='minor', alpha=0.25, linestyle=':', linewidth=0.5)
    
    ax1.set_xlabel(f'{start_labels[0]} (meters) - relative to center', fontsize=16, fontweight='bold')
    ax1.set_ylabel(f'{start_labels[1]} (meters) - relative to center', fontsize=16, fontweight='bold')
    
    title_text = f'{start_face_name.upper()} DRILLING TEMPLATE - 1:1 SCALE\n'
    title_text += f'Anchor Point Locations (Origin at Center)\n'
    title_text += f'⚠️ {start_mirror_note}'
    
    ax1.set_title(title_text, fontsize=18, fontweight='bold', pad=20)
    ax1.set_aspect('equal', adjustable='box')
    ax1.legend(loc='upper right', fontsize=13)
    
    plt.tight_layout()
    fig1.savefig(os.path.join(output_dir, f'{start_face_name}_template.png'), dpi=100, bbox_inches='tight', facecolor='white')
    fig1.savefig(os.path.join(output_dir, f'{start_face_name}_template.svg'), bbox_inches='tight', facecolor='white')
    fig1.savefig(os.path.join(output_dir, f'{start_face_name}_template.pdf'), bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"✓ Saved {start_face_name} template (Mirroring: {start_mirror_note})")
    
    # ===== END FACE TEMPLATE =====
    fig2 = plt.figure(figsize=(fig_width, fig_height))
    ax2 = fig2.add_subplot(111)
    
    if end_curve_relative is not None:
        ax2.plot(end_curve_relative[:, 0], end_curve_relative[:, 1], 
                 'r:', linewidth=3, alpha=0.7, label='Intersection curve', zorder=4)
    
    ax2.scatter(end_points_relative[:, 0], end_points_relative[:, 1], c='red', s=300, 
               marker='+', linewidths=4, zorder=6, label='Anchor points')
    
    valid_idx = 0
    for i in range(len(end_face_points)):
        if end_valid[i]:
            coord_text = f'{i+1}\n({end_points_relative[valid_idx, 0]:.3f}, {end_points_relative[valid_idx, 1]:.3f})'
            ax2.text(end_points_relative[valid_idx, 0] + 0.03, end_points_relative[valid_idx, 1] + 0.03, coord_text, 
                    fontsize=11, fontweight='bold', color='black',
                    bbox=dict(boxstyle='round,pad=0.5', facecolor='yellow', alpha=0.8))
            valid_idx += 1
    
    ax2.scatter(0, 0, c='blue', s=500, marker='x', linewidths=6, zorder=5, label='CENTER (Origin)')
    ax2.text(0.05, 0.05, 'ORIGIN\n(0, 0)', fontsize=14, fontweight='bold', color='blue')
    
    for i in range(len(end_points_relative)):
        ax2.plot([0, end_points_relative[i, 0]], [0, end_points_relative[i, 1]], 
                'gray', linestyle=':', linewidth=1.5, alpha=0.5, zorder=3)
    
    ax2.set_xlim(-max_dist, max_dist)
    ax2.set_ylim(-max_dist, max_dist)
    ax2.axhline(y=0, color='black', linewidth=2, alpha=0.8)
    ax2.axvline(x=0, color='black', linewidth=2, alpha=0.8)
    ax2.grid(True, alpha=0.5, linestyle='-', linewidth=0.8, which='both')
    ax2.minorticks_on()
    ax2.grid(True, which='minor', alpha=0.25, linestyle=':', linewidth=0.5)
    
    ax2.set_xlabel(f'{end_labels[0]} (meters) - relative to center', fontsize=16, fontweight='bold')
    ax2.set_ylabel(f'{end_labels[1]} (meters) - relative to center', fontsize=16, fontweight='bold')
    
    title_text = f'{end_face_name.upper()} DRILLING TEMPLATE - 1:1 SCALE\n'
    title_text += f'Anchor Point Locations (Origin at Center)\n'
    title_text += f'⚠️ {end_mirror_note}'
    
    ax2.set_title(title_text, fontsize=18, fontweight='bold', pad=20)
    ax2.set_aspect('equal', adjustable='box')
    ax2.legend(loc='upper right', fontsize=13)
    
    plt.tight_layout()
    fig2.savefig(os.path.join(output_dir, f'{end_face_name}_template.png'), dpi=100, bbox_inches='tight', facecolor='white')
    fig2.savefig(os.path.join(output_dir, f'{end_face_name}_template.svg'), bbox_inches='tight', facecolor='white')
    fig2.savefig(os.path.join(output_dir, f'{end_face_name}_template.pdf'), bbox_inches='tight', facecolor='white')
    plt.close()
    print(f"✓ Saved {end_face_name} template (Mirroring: {end_mirror_note})")


def print_attachment_points(start_face_points, end_face_points, start_face_name, end_face_name, 
                            start_point_3d, end_point_3d, output_dir, args):
    """Print the coordinates of anchor points and save to file."""
    
    # Project to 2D for each face
    start_2d, start_labels = project_to_2d(start_face_points, start_face_name)
    end_2d, end_labels = project_to_2d(end_face_points, end_face_name)
    
    start_axis_2d, _ = project_to_2d(np.array([start_point_3d]), start_face_name)
    end_axis_2d, _ = project_to_2d(np.array([end_point_3d]), end_face_name)
    
    # Get mirroring info
    start_mirror_note = get_mirroring_note(start_face_name)
    end_mirror_note = get_mirroring_note(end_face_name)
    
    # Create output string
    output = []
    output.append("=" * 90)
    output.append("DRUM SUSPENSION - WIRE ANCHOR POINTS")
    output.append("=" * 90)
    output.append(f"\nCOORDINATE SYSTEM:")
    output.append(f"  Origin: Left corner (0, 0, 0)")
    output.append(f"  X axis: Going right (to back wall, max={HALL_X_MAX})")
    output.append(f"  Y axis: Going into scene (to lateral wall, max={HALL_Y_MAX})")
    output.append(f"  Z axis: Going up (height, max={HALL_Z_MAX})")
    
    output.append(f"\n⚠️ TEMPLATE MIRRORING (for inside-cube installation):")
    output.append(f"  {start_face_name}: {start_mirror_note}")
    output.append(f"  {end_face_name}: {end_mirror_note}")
    
    output.append(f"\nINPUT PARAMETERS:")
    output.append(f"  Project name: {args.name}")
    output.append(f"  Start point: ({args.start[0]:.2f}, {args.start[1]:.2f}, {args.start[2]:.2f}) m")
    output.append(f"  Detected face: {start_face_name}")
    output.append(f"  End point: ({args.end[0]:.2f}, {args.end[1]:.2f}, {args.end[2]:.2f}) m")
    output.append(f"  Detected face: {end_face_name}")
    output.append(f"  Cylinder bottom position: {args.position:.2f} (along axis)")
    output.append(f"  Show cylinder: {args.show_cylinder}")
    
    output.append(f"\nDrum Specifications:")
    output.append(f"  Diameter: {args.diameter:.4f} m")
    output.append(f"  Radius: {args.diameter/2:.4f} m")
    output.append(f"  Depth: {args.depth:.2f} m")
    output.append(f"  Attachment points per rim: {args.num_points}")
    
    output.append("\n" + "=" * 90)
    output.append(f"{start_face_name.upper()} ANCHOR POINTS")
    output.append("=" * 90)
    output.append(f"Reference center: ({start_axis_2d[0][0]:.4f}, {start_axis_2d[0][1]:.4f})")
    output.append("-" * 90)
    output.append(f"{'Point':<8} {'3D X (m)':<12} {'3D Y (m)':<12} {'3D Z (m)':<12} {f'2D {start_labels[0]} (m)':<15} {f'2D {start_labels[1]} (m)':<15}")
    output.append("-" * 90)
    for i in range(len(start_face_points)):
        output.append(f"{i+1:<8} {start_face_points[i, 0]:<12.4f} {start_face_points[i, 1]:<12.4f} {start_face_points[i, 2]:<12.4f} "
              f"{start_2d[i, 0]:<15.4f} {start_2d[i, 1]:<15.4f}")
    
    output.append("\n" + "=" * 90)
    output.append(f"{end_face_name.upper()} ANCHOR POINTS")
    output.append("=" * 90)
    output.append(f"Reference center: ({end_axis_2d[0][0]:.4f}, {end_axis_2d[0][1]:.4f})")
    output.append("-" * 90)
    output.append(f"{'Point':<8} {'3D X (m)':<12} {'3D Y (m)':<12} {'3D Z (m)':<12} {f'2D {end_labels[0]} (m)':<15} {f'2D {end_labels[1]} (m)':<15}")
    output.append("-" * 90)
    for i in range(len(end_face_points)):
        output.append(f"{i+1:<8} {end_face_points[i, 0]:<12.4f} {end_face_points[i, 1]:<12.4f} {end_face_points[i, 2]:<12.4f} "
              f"{end_2d[i, 0]:<15.4f} {end_2d[i, 1]:<15.4f}")
    output.append("=" * 90)
    
    # Check for invalid points
    start_valid_count = (~np.isnan(start_face_points).any(axis=1)).sum()
    end_valid_count = (~np.isnan(end_face_points).any(axis=1)).sum()
    
    if start_valid_count < len(start_face_points):
        output.append(f"\nWARNING: {len(start_face_points) - start_valid_count} points on {start_face_name} are outside face bounds")
    if end_valid_count < len(end_face_points):
        output.append(f"WARNING: {len(end_face_points) - end_valid_count} points on {end_face_name} are outside face bounds")
    
    # Print to console
    for line in output:
        print(line)
    
    # Save to file
    with open(os.path.join(output_dir, 'coordinates.txt'), 'w') as f:
        f.write('\n'.join(output))
    print(f"\n✓ Saved coordinates to coordinates.txt")


def visualize_cylinder_suspension(bottom_points, top_points, bottom_center, top_center, 
                                  radius, perp1, perp2, axis_unit, start_point, end_point,
                                  start_face_name, end_face_name, output_dir, show_cylinder=True):
    """Create 3D visualization of the suspended drum."""
    
    fig = plt.figure(figsize=(16, 12))
    ax = fig.add_subplot(111, projection='3d')
    
    if show_cylinder:
        # Generate and plot cylinder surface
        X, Y, Z = generate_cylinder_surface(bottom_center, top_center, radius, perp1, perp2)
        ax.plot_surface(X, Y, Z, alpha=0.3, color='cyan', edgecolor='none', shade=True)
        
        # Plot cylinder edges
        theta_fine = np.linspace(0, 2*np.pi, 100)
        
        bottom_circle_x = bottom_center[0] + radius * (np.cos(theta_fine) * perp1[0] + np.sin(theta_fine) * perp2[0])
        bottom_circle_y = bottom_center[1] + radius * (np.cos(theta_fine) * perp1[1] + np.sin(theta_fine) * perp2[1])
        bottom_circle_z = bottom_center[2] + radius * (np.cos(theta_fine) * perp1[2] + np.sin(theta_fine) * perp2[2])
        ax.plot(bottom_circle_x, bottom_circle_y, bottom_circle_z, 'b-', linewidth=2, label='Bottom rim')
        
        top_circle_x = top_center[0] + radius * (np.cos(theta_fine) * perp1[0] + np.sin(theta_fine) * perp2[0])
        top_circle_y = top_center[1] + radius * (np.cos(theta_fine) * perp1[1] + np.sin(theta_fine) * perp2[1])
        top_circle_z = top_center[2] + radius * (np.cos(theta_fine) * perp1[2] + np.sin(theta_fine) * perp2[2])
        ax.plot(top_circle_x, top_circle_y, top_circle_z, 'r-', linewidth=2, label='Top rim')
        
        # Plot attachment points
        ax.scatter(bottom_points[:, 0], bottom_points[:, 1], bottom_points[:, 2], 
                  c='blue', s=50, marker='o', zorder=10, label='Bottom attachment points')
        ax.scatter(top_points[:, 0], top_points[:, 1], top_points[:, 2], 
                  c='red', s=50, marker='o', zorder=10, label='Top attachment points')
    
    # Plot the axis line (always show)
    ax.plot([start_point[0], end_point[0]], 
           [start_point[1], end_point[1]], 
           [start_point[2], end_point[2]], 
           'g--', linewidth=2, label='Wire axis', alpha=0.7)
    
    # Plot suspension wires (always show, skip nan points)
    num_points = len(bottom_points)
    for i in range(num_points):
        start_intersection = find_plane_intersection(bottom_points[i], -axis_unit, start_face_name)
        if start_intersection is not None and not np.isnan(start_intersection).any():
            ax.plot([start_intersection[0], bottom_points[i, 0]], 
                   [start_intersection[1], bottom_points[i, 1]], 
                   [start_intersection[2], bottom_points[i, 2]], 
                   'darkblue', alpha=0.6, linewidth=2.5)
        
        end_intersection = find_plane_intersection(top_points[i], axis_unit, end_face_name)
        if end_intersection is not None and not np.isnan(end_intersection).any():
            ax.plot([top_points[i, 0], end_intersection[0]], 
                   [top_points[i, 1], end_intersection[1]], 
                   [top_points[i, 2], end_intersection[2]], 
                   'darkred', alpha=0.6, linewidth=2.5)
    
    # Plot cube faces
    xx, yy = np.meshgrid([0, HALL_X_MAX], [0, HALL_Y_MAX])
    ax.plot_surface(xx, yy, np.zeros_like(xx), alpha=0.1, color='gray')  # floor
    ax.plot_surface(xx, yy, np.ones_like(xx) * HALL_Z_MAX, alpha=0.1, color='gray')  # ceiling
    
    yy, zz = np.meshgrid([0, HALL_Y_MAX], [0, HALL_Z_MAX])
    ax.plot_surface(np.zeros_like(yy), yy, zz, alpha=0.1, color='gray')  # left wall (x=0)
    ax.plot_surface(np.ones_like(yy) * HALL_X_MAX, yy, zz, alpha=0.1, color='gray')  # back wall (x=max)
    
    xx, zz = np.meshgrid([0, HALL_X_MAX], [0, HALL_Z_MAX])
    ax.plot_surface(xx, np.zeros_like(xx), zz, alpha=0.1, color='gray')  # front wall (y=0)
    ax.plot_surface(xx, np.ones_like(xx) * HALL_Y_MAX, zz, alpha=0.1, color='gray')  # lateral wall (y=max)
    
    # Set axis labels - X right, Y into scene, Z up
    ax.set_xlabel('X (meters) →', fontsize=12, fontweight='bold')
    ax.set_ylabel('Y (meters) ↗', fontsize=12, fontweight='bold')
    ax.set_zlabel('Z (meters) ↑', fontsize=12, fontweight='bold')
    
    title = f'Wire Suspension: {start_face_name} to {end_face_name}\n'
    title += f'Coordinate System: X→right, Y→into scene, Z→up'
    if show_cylinder:
        title += ' (with Drum)'
    else:
        title += ' (Wires Only)'
    
    ax.set_title(title, fontsize=14, fontweight='bold')
    ax.legend(loc='upper right', fontsize=10)
    
    ax.set_xlim(0, HALL_X_MAX)
    ax.set_ylim(0, HALL_Y_MAX)
    ax.set_zlim(0, HALL_Z_MAX)
    ax.set_box_aspect([HALL_X_MAX, HALL_Y_MAX, HALL_Z_MAX])
    ax.view_init(elev=20, azim=45)
    
    plt.tight_layout()
    plt.savefig(os.path.join(output_dir, '3d_visualization.png'), dpi=300, bbox_inches='tight')
    print("✓ Saved 3D visualization")
    plt.show()


def parse_arguments():
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(
        description='Calculate drum suspension wire anchor points between two faces of a cube.',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Floor to ceiling (17" tom drum)
  python %(prog)s --name "tom_17_floor_ceiling" --start 3.0 4.5 0.0 --end 5.3 5.8 4.5
  
  # Wall to wall (wires only, no cylinder)
  python %(prog)s --name "wire_wall_test" --start 0.0 3.0 2.0 --end 9.0 5.0 3.0 --no-cylinder
  
  # Custom drum size with different position
  python %(prog)s --name "custom_drum" --start 2.0 3.0 0.0 --end 4.0 4.0 4.5 \\
                  --diameter 0.5 --depth 0.45 --position 0.4 --num-points 10

Coordinate System:
  Origin: Left corner (0, 0, 0)
  X axis: Going right (to back wall, max=9.0 m)
  Y axis: Going into scene (to lateral wall, max=6.0 m)
  Z axis: Going up (height, max=4.5 m)
  
Valid faces are automatically detected:
  - floor: z=0
  - ceiling: z=4.5
  - wall_x0 (left): x=0
  - wall_x_max (back/right): x=9.0
  - wall_y0 (front): y=0
  - wall_y_max (lateral/into scene): y=6.0

Mirroring for Inside-Cube Installation:
  Templates are automatically mirrored to match the perspective when you're 
  inside the cube looking at each face. This ensures coordinates on the printed 
  template align with your physical measurements.
        """
    )
    
    # Required arguments
    parser.add_argument('--name', '-n', type=str, required=True,
                      help='Project name for output directory')
    parser.add_argument('--start', '-s', type=float, nargs=3, required=True,
                      metavar=('X', 'Y', 'Z'),
                      help='Start point coordinates (x y z) in meters')
    parser.add_argument('--end', '-e', type=float, nargs=3, required=True,
                      metavar=('X', 'Y', 'Z'),
                      help='End point coordinates (x y z) in meters')
    
    # Optional drum specifications
    parser.add_argument('--diameter', '-d', type=float, default=0.4318,
                      help='Drum diameter in meters (default: 0.4318 for 17" tom)')
    parser.add_argument('--depth', type=float, default=0.40,
                      help='Drum depth in meters (default: 0.40)')
    parser.add_argument('--position', '-p', type=float, default=0.33,
                      help='Cylinder bottom position along axis, 0 to 1 (default: 0.33)')
    parser.add_argument('--num-points', type=int, default=8,
                      help='Number of attachment points per rim (default: 8)')
    
    # Visualization options
    parser.add_argument('--no-cylinder', action='store_true',
                      help='Show only wires without cylinder visualization')
    
    args = parser.parse_args()
    
    # Add computed property
    args.show_cylinder = not args.no_cylinder
    
    # Validate position
    if not 0 <= args.position <= 1:
        parser.error("--position must be between 0 and 1")
    
    # Validate num_points
    if args.num_points < 3:
        parser.error("--num-points must be at least 3")
    
    return args


# ========== MAIN EXECUTION ==========
def main():
    """Main execution function."""
    
    # Parse command line arguments
    args = parse_arguments()
    
    print("=" * 90)
    print("GENERALIZED DRUM SUSPENSION CALCULATOR")
    print("=" * 90)
    print(f"\nCOORDINATE SYSTEM:")
    print(f"  Origin: Left corner (0, 0, 0)")
    print(f"  X axis: Going right (to back wall, max={HALL_X_MAX} m)")
    print(f"  Y axis: Going into scene (to lateral wall, max={HALL_Y_MAX} m)")
    print(f"  Z axis: Going up (height, max={HALL_Z_MAX} m)")
    
    # Create output directory
    output_dir = create_output_directory(args.name)
    print(f"\nOutput directory: {output_dir}")
    
    # Automatically detect faces from coordinates
    try:
        start_point = np.array(args.start)
        end_point = np.array(args.end)
        
        start_face_name = detect_face(args.start[0], args.start[1], args.start[2])
        end_face_name = detect_face(args.end[0], args.end[1], args.end[2])
        
        print(f"\nDetected faces:")
        print(f"  Start point ({args.start[0]:.2f}, {args.start[1]:.2f}, {args.start[2]:.2f}) → {start_face_name}")
        print(f"  End point ({args.end[0]:.2f}, {args.end[1]:.2f}, {args.end[2]:.2f}) → {end_face_name}")
        
    except ValueError as e:
        print(f"\nERROR: {e}")
        sys.exit(1)
    
    # Calculate drum radius
    drum_radius = args.diameter / 2
    
    # Calculate cylinder centers
    bottom_center, top_center = calculate_cylinder_centers(
        start_point, end_point, args.position, args.depth
    )
    
    # Calculate attachment points
    bottom_points, top_points, perp1, perp2, axis_unit = calculate_cylinder_attachment_points(
        bottom_center, top_center, drum_radius, args.num_points
    )
    
    # Calculate face intersection points (handle None returns)
    start_face_points = np.zeros((args.num_points, 3))
    end_face_points = np.zeros((args.num_points, 3))
    
    for i in range(args.num_points):
        start_intersection = find_plane_intersection(bottom_points[i], -axis_unit, start_face_name)
        if start_intersection is not None:
            start_face_points[i] = start_intersection
        else:
            start_face_points[i] = [np.nan, np.nan, np.nan]
        
        end_intersection = find_plane_intersection(top_points[i], axis_unit, end_face_name)
        if end_intersection is not None:
            end_face_points[i] = end_intersection
        else:
            end_face_points[i] = [np.nan, np.nan, np.nan]
    
    # Print results
    print_attachment_points(start_face_points, end_face_points, start_face_name, end_face_name, 
                           start_point, end_point, output_dir, args)
    
    # Create templates
    print("\nGenerating drilling templates...")
    plot_template(start_face_points, end_face_points, start_face_name, end_face_name,
                 start_point, end_point, bottom_center, top_center, 
                 drum_radius, perp1, perp2, axis_unit, output_dir)
    
    # Visualize 3D
    visualize_cylinder_suspension(bottom_points, top_points, bottom_center, top_center, 
                                  drum_radius, perp1, perp2, axis_unit,
                                  start_point, end_point, start_face_name, end_face_name, 
                                  output_dir, show_cylinder=args.show_cylinder)
    
    print("\n" + "=" * 90)
    print("COMPLETE!")
    print(f"All files saved to: {output_dir}")
    print("=" * 90)


if __name__ == "__main__":
    main()
