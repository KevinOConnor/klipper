# Mesh Bed Leveling
#
# Copyright (C) 2018  Kevin O'Connor <kevin@koconnor.net>
# Copyright (C) 2018-2019 Eric Callahan <arksine.code@gmail.com>
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging, math, json, collections
from . import probe

PROFILE_VERSION = 1
PROFILE_OPTIONS = {
    'min_x': float, 'max_x': float, 'min_y': float, 'max_y': float,
    'x_count': int, 'y_count': int, 'mesh_x_pps': int, 'mesh_y_pps': int,
    'algo': str, 'tension': float
}

class BedMeshError(Exception):
    pass

# PEP 485 isclose()
def isclose(a, b, rel_tol=1e-09, abs_tol=0.0):
    return abs(a-b) <= max(rel_tol * max(abs(a), abs(b)), abs_tol)

# return true if a coordinate is within the region
# specified by min_c and max_c
def within(coord, min_c, max_c, tol=0.0):
    return (max_c[0] + tol) >= coord[0] >= (min_c[0] - tol) and \
        (max_c[1] + tol) >= coord[1] >= (min_c[1] - tol)

# Constrain value between min and max
def constrain(val, min_val, max_val):
    return min(max_val, max(min_val, val))

# Linear interpolation between two values
def lerp(t, v0, v1):
    return (1. - t) * v0 + t * v1

# retreive commma separated pair from config
def parse_pair(config, param, check=True, cast=float,
               minval=None, maxval=None):
    val = config.get(*param).strip().split(',', 1)
    pair = tuple(cast(p.strip()) for p in val)
    if check and len(pair) != 2:
        raise config.error(
            "bed_mesh: malformed '%s' value: %s"
            % (param[0], config.get(*param)))
    elif len(pair) == 1:
        pair = (pair[0], pair[0])
    if minval is not None:
        if pair[0] < minval or pair[1] < minval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a minimum of %s"
                % (param[0], str(minval)))
    if maxval is not None:
        if pair[0] > maxval or pair[1] > maxval:
            raise config.error(
                "Option '%s' in section bed_mesh must have a maximum of %s"
                % (param[0], str(maxval)))
    return pair


class BedMesh:
    FADE_DISABLE = 0x7FFFFFFF
    def __init__(self, config):
        self.printer = config.get_printer()
        self.printer.register_event_handler("klippy:connect",
                                            self.handle_connect)
        self.last_position = [0., 0., 0., 0.]
        self.bmc = BedMeshCalibrate(config, self)
        self.z_mesh = None
        self.toolhead = None
        self.horizontal_move_z = config.getfloat('horizontal_move_z', 5.)
        self.fade_start = config.getfloat('fade_start', 1.)
        self.fade_end = config.getfloat('fade_end', 0.)
        self.fade_dist = self.fade_end - self.fade_start
        if self.fade_dist <= 0.:
            self.fade_start = self.fade_end = self.FADE_DISABLE
        self.log_fade_complete = False
        self.base_fade_target = config.getfloat('fade_target', None)
        self.fade_target = 0.
        self.gcode = self.printer.lookup_object('gcode')
        self.splitter = MoveSplitter(config, self.gcode)
        # setup persistent storage
        self.pmgr = ProfileManager(config, self)
        self.save_profile = self.pmgr.save_profile
        # register gcodes
        self.gcode.register_command(
            'BED_MESH_OUTPUT', self.cmd_BED_MESH_OUTPUT,
            desc=self.cmd_BED_MESH_OUTPUT_help)
        self.gcode.register_command(
            'BED_MESH_MAP', self.cmd_BED_MESH_MAP,
            desc=self.cmd_BED_MESH_MAP_help)
        self.gcode.register_command(
            'BED_MESH_CLEAR', self.cmd_BED_MESH_CLEAR,
            desc=self.cmd_BED_MESH_CLEAR_help)
        self.gcode.register_command(
            'BED_MESH_OFFSET', self.cmd_BED_MESH_OFFSET,
            desc=self.cmd_BED_MESH_OFFSET_help)
        # Register transform
        gcode_move = self.printer.load_object(config, 'gcode_move')
        gcode_move.set_move_transform(self)
    def handle_connect(self):
        self.toolhead = self.printer.lookup_object('toolhead')
        self.bmc.print_generated_points(logging.info)
        self.pmgr.initialize()
    def set_mesh(self, mesh):
        if mesh is not None and self.fade_end != self.FADE_DISABLE:
            self.log_fade_complete = True
            if self.base_fade_target is None:
                self.fade_target = mesh.avg_z
            else:
                self.fade_target = self.base_fade_target
                min_z, max_z = mesh.get_z_range()
                if (not min_z <= self.fade_target <= max_z and
                        self.fade_target != 0.):
                    # fade target is non-zero, out of mesh range
                    err_target = self.fade_target
                    self.z_mesh = None
                    self.fade_target = 0.
                    raise self.gcode.error(
                        "bed_mesh: ERROR, fade_target lies outside of mesh z "
                        "range\nmin: %.4f, max: %.4f, fade_target: %.4f"
                        % (min_z, max_z, err_target))
            min_z, max_z = mesh.get_z_range()
            if self.fade_dist <= max(abs(min_z), abs(max_z)):
                self.z_mesh = None
                self.fade_target = 0.
                raise self.gcode.error(
                    "bed_mesh:  Mesh extends outside of the fade range, "
                    "please see the fade_start and fade_end options in"
                    "example-extras.cfg. fade distance: %.2f mesh min: %.4f"
                    "mesh max: %.4f" % (self.fade_dist, min_z, max_z))
        else:
            self.fade_target = 0.
        self.z_mesh = mesh
        self.splitter.initialize(mesh, self.fade_target)
        # cache the current position before a transform takes place
        gcode_move = self.printer.lookup_object('gcode_move')
        gcode_move.reset_last_position()
    def get_z_factor(self, z_pos):
        if z_pos >= self.fade_end:
            return 0.
        elif z_pos >= self.fade_start:
            return (self.fade_end - z_pos) / self.fade_dist
        else:
            return 1.
    def get_position(self):
        # Return last, non-transformed position
        if self.z_mesh is None:
            # No mesh calibrated, so send toolhead position
            self.last_position[:] = self.toolhead.get_position()
            self.last_position[2] -= self.fade_target
        else:
            # return current position minus the current z-adjustment
            x, y, z, e = self.toolhead.get_position()
            max_adj = self.z_mesh.calc_z(x, y)
            factor = 1.
            z_adj = max_adj - self.fade_target
            if min(z, (z - max_adj)) >= self.fade_end:
                # Fade out is complete, no factor
                factor = 0.
            elif max(z, (z - max_adj)) >= self.fade_start:
                # Likely in the process of fading out adjustment.
                # Because we don't yet know the gcode z position, use
                # algebra to calculate the factor from the toolhead pos
                factor = ((self.fade_end + self.fade_target - z) /
                          (self.fade_dist - z_adj))
                factor = constrain(factor, 0., 1.)
            final_z_adj = factor * z_adj + self.fade_target
            self.last_position[:] = [x, y, z - final_z_adj, e]
        return list(self.last_position)
    def move(self, newpos, speed):
        factor = self.get_z_factor(newpos[2])
        if self.z_mesh is None or not factor:
            # No mesh calibrated, or mesh leveling phased out.
            x, y, z, e = newpos
            if self.log_fade_complete:
                self.log_fade_complete = False
                logging.info(
                    "bed_mesh fade complete: Current Z: %.4f fade_target: %.4f "
                    % (z, self.fade_target))
            self.toolhead.move([x, y, z + self.fade_target, e], speed)
        else:
            self.splitter.build_move(self.last_position, newpos, factor)
            while not self.splitter.traverse_complete:
                split_move = self.splitter.split()
                if split_move:
                    self.toolhead.move(split_move, speed)
                else:
                    raise self.gcode.error(
                        "Mesh Leveling: Error splitting move ")
        self.last_position[:] = newpos
    def get_status(self, eventtime=None):
        status = {
            "profile_name": "",
            "mesh_min": (0., 0.),
            "mesh_max": (0., 0.),
            "probed_matrix": [[]],
            "mesh_matrix": [[]]
        }
        if self.z_mesh is not None:
            params = self.z_mesh.get_mesh_params()
            mesh_min = (params['min_x'], params['min_y'])
            mesh_max = (params['max_x'], params['max_y'])
            probed_matrix = self.z_mesh.get_probed_matrix()
            mesh_matrix = self.z_mesh.get_mesh_matrix()
            status['profile_name'] = self.pmgr.get_current_profile()
            status['mesh_min'] = mesh_min
            status['mesh_max'] = mesh_max
            status['probed_matrix'] = probed_matrix
            status['mesh_matrix'] = mesh_matrix
        return status
    def get_mesh(self):
        return self.z_mesh
    cmd_BED_MESH_OUTPUT_help = "Retrieve interpolated grid of probed z-points"
    def cmd_BED_MESH_OUTPUT(self, gcmd):
        if gcmd.get_int('PGP', 0):
            # Print Generated Points instead of mesh
            self.bmc.print_generated_points(gcmd.respond_info)
        elif self.z_mesh is None:
            gcmd.respond_info("Bed has not been probed")
        else:
            self.z_mesh.print_probed_matrix(gcmd.respond_info)
            self.z_mesh.print_mesh(gcmd.respond_raw, self.horizontal_move_z)
    cmd_BED_MESH_MAP_help = "Serialize mesh and output to terminal"
    def cmd_BED_MESH_MAP(self, gcmd):
        if self.z_mesh is not None:
            params = self.z_mesh.get_mesh_params()
            outdict = {
                'mesh_min': (params['min_x'], params['min_y']),
                'mesh_max': (params['max_x'], params['max_y']),
                'z_positions': self.z_mesh.get_probed_matrix()}
            gcmd.respond_raw("mesh_map_output " + json.dumps(outdict))
        else:
            gcmd.respond_info("Bed has not been probed")
    cmd_BED_MESH_CLEAR_help = "Clear the Mesh so no z-adjustment is made"
    def cmd_BED_MESH_CLEAR(self, gcmd):
        self.set_mesh(None)
    cmd_BED_MESH_OFFSET_help = "Add X/Y offsets to the mesh lookup"
    def cmd_BED_MESH_OFFSET(self, gcmd):
        if self.z_mesh is not None:
            offsets = [None, None]
            for i, axis in enumerate(['X', 'Y']):
                offsets[i] = gcmd.get_float(axis, None)
            self.z_mesh.set_mesh_offsets(offsets)
            gcode_move = self.printer.lookup_object('gcode_move')
            gcode_move.reset_last_position()
        else:
            gcmd.respond_info("No mesh loaded to offset")


class BedMeshCalibrate:
    ALGOS = ['lagrange', 'bicubic']
    def __init__(self, config, bedmesh):
        self.printer = config.get_printer()
        self.orig_config = {'radius': None, 'origin': None}
        self.radius = self.origin = None
        self.mesh_min = self.mesh_max = (0., 0.)
        self.relative_reference_index = config.getint(
            'relative_reference_index', None)
        self.faulty_regions = []
        self.substituted_indices = collections.OrderedDict()
        self.orig_config['rri'] = self.relative_reference_index
        self.bedmesh = bedmesh
        self.mesh_config = collections.OrderedDict()
        self._init_mesh_config(config)
        self._generate_points(config.error)
        self.orig_points = self.points
        self.probe_helper = probe.ProbePointsHelper(
            config, self.probe_finalize, self._get_adjusted_points())
        self.probe_helper.minimum_points(3)
        self.probe_helper.use_xy_offsets(True)
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command(
            'BED_MESH_CALIBRATE', self.cmd_BED_MESH_CALIBRATE,
            desc=self.cmd_BED_MESH_CALIBRATE_help)
    def _generate_points(self, error):
        x_cnt = self.mesh_config['x_count']
        y_cnt = self.mesh_config['y_count']
        min_x, min_y = self.mesh_min
        max_x, max_y = self.mesh_max
        x_dist = (max_x - min_x) / (x_cnt - 1)
        y_dist = (max_y - min_y) / (y_cnt - 1)
        # floor distances down to next hundredth
        x_dist = math.floor(x_dist * 100) / 100
        y_dist = math.floor(y_dist * 100) / 100
        if x_dist <= 1. or y_dist <= 1.:
            raise error("bed_mesh: min/max points too close together")

        if self.radius is not None:
            # round bed, min/max needs to be recalculated
            y_dist = x_dist
            new_r = (x_cnt / 2) * x_dist
            min_x = min_y = -new_r
            max_x = max_y = new_r
        else:
            # rectangular bed, only re-calc max_x
            max_x = min_x + x_dist * (x_cnt - 1)
        pos_y = min_y
        points = []
        for i in range(y_cnt):
            for j in range(x_cnt):
                if not i % 2:
                    # move in positive directon
                    pos_x = min_x + j * x_dist
                else:
                    # move in negative direction
                    pos_x = max_x - j * x_dist
                if self.radius is None:
                    # rectangular bed, append
                    points.append((pos_x, pos_y))
                else:
                    # round bed, check distance from origin
                    dist_from_origin = math.sqrt(pos_x*pos_x + pos_y*pos_y)
                    if dist_from_origin <= self.radius:
                        points.append(
                            (self.origin[0] + pos_x, self.origin[1] + pos_y))
            pos_y += y_dist
        self.points = points
        if not self.faulty_regions:
            return
        # Check to see if any points fall within faulty regions
        last_y = self.points[0][1]
        is_reversed = False
        for i, coord in enumerate(self.points):
            if not isclose(coord[1], last_y):
                is_reversed = not is_reversed
            last_y = coord[1]
            adj_coords = []
            for min_c, max_c in self.faulty_regions:
                if within(coord, min_c, max_c, tol=.00001):
                    # Point lies within a faulty region
                    adj_coords = [
                        (min_c[0], coord[1]), (coord[0], min_c[1]),
                        (coord[0], max_c[1]), (max_c[0], coord[1])]
                    if is_reversed:
                        # Swap first and last points for zig-zag pattern
                        first = adj_coords[0]
                        adj_coords[0] = adj_coords[-1]
                        adj_coords[-1] = first
                    break
            if not adj_coords:
                # coord is not located within a faulty region
                continue
            valid_coords = []
            for ac in adj_coords:
                # make sure that coordinates are within the mesh boundary
                if self.radius is None:
                    if within(ac, (min_x, min_y), (max_x, max_y), .000001):
                        valid_coords.append(ac)
                else:
                    dist_from_origin = math.sqrt(ac[0]*ac[0] + ac[1]*ac[1])
                    if dist_from_origin <= self.radius:
                        valid_coords.append(ac)
            if not valid_coords:
                raise error("bed_mesh: Unable to generate coordinates"
                            " for faulty region at index: %d" % (i))
            self.substituted_indices[i] = valid_coords
    def print_generated_points(self, print_func):
        x_offset = y_offset = 0.
        probe = self.printer.lookup_object('probe', None)
        if probe is not None:
            x_offset, y_offset = probe.get_offsets()[:2]
        print_func("bed_mesh: generated points\nIndex"
                   " |  Tool Adjusted  |   Probe")
        for i, (x, y) in enumerate(self.points):
            adj_pt = "(%.1f, %.1f)" % (x - x_offset, y - y_offset)
            mesh_pt = "(%.1f, %.1f)" % (x, y)
            print_func(
                "  %-4d| %-16s| %s" % (i, adj_pt, mesh_pt))
        if self.relative_reference_index is not None:
            rri = self.relative_reference_index
            print_func(
                "bed_mesh: relative_reference_index %d is (%.2f, %.2f)"
                % (rri, self.points[rri][0], self.points[rri][1]))
        if self.substituted_indices:
            print_func("bed_mesh: faulty region points")
            for i, v in self.substituted_indices.items():
                pt = self.points[i]
                print_func("%d (%.2f, %.2f), substituted points: %s"
                           % (i, pt[0], pt[1], repr(v)))
    def _init_mesh_config(self, config):
        mesh_cfg = self.mesh_config
        orig_cfg = self.orig_config
        self.radius = config.getfloat('mesh_radius', None, above=0.)
        if self.radius is not None:
            self.origin = parse_pair(config, ('mesh_origin', "0, 0"))
            x_cnt = y_cnt = config.getint('round_probe_count', 5, minval=3)
            # round beds must have an odd number of points along each axis
            if not x_cnt & 1:
                raise config.error(
                    "bed_mesh: probe_count must be odd for round beds")
            # radius may have precision to .1mm
            self.radius = math.floor(self.radius * 10) / 10
            orig_cfg['radius'] = self.radius
            orig_cfg['origin'] = self.origin
            min_x = min_y = -self.radius
            max_x = max_y = self.radius
        else:
            # rectangular
            x_cnt, y_cnt = parse_pair(
                config, ('probe_count', '3'), check=False, cast=int, minval=3)
            min_x, min_y = parse_pair(config, ('mesh_min',))
            max_x, max_y = parse_pair(config, ('mesh_max',))
            if max_x <= min_x or max_y <= min_y:
                raise config.error('bed_mesh: invalid min/max points')
        orig_cfg['x_count'] = mesh_cfg['x_count'] = x_cnt
        orig_cfg['y_count'] = mesh_cfg['y_count'] = y_cnt
        orig_cfg['mesh_min'] = self.mesh_min = (min_x, min_y)
        orig_cfg['mesh_max'] = self.mesh_max = (max_x, max_y)

        pps = parse_pair(config, ('mesh_pps', '2'), check=False,
                         cast=int, minval=0)
        orig_cfg['mesh_x_pps'] = mesh_cfg['mesh_x_pps'] = pps[0]
        orig_cfg['mesh_y_pps'] = mesh_cfg['mesh_y_pps'] = pps[1]
        orig_cfg['algo'] = mesh_cfg['algo'] = \
            config.get('algorithm', 'lagrange').strip().lower()
        orig_cfg['tension'] = mesh_cfg['tension'] = config.getfloat(
            'bicubic_tension', .2, minval=0., maxval=2.)
        for i in list(range(1, 100, 1)):
            min_opt = "faulty_region_%d_min" % (i,)
            max_opt = "faulty_region_%d_max" % (i,)
            if config.get(min_opt, None) is None:
                break
            start = parse_pair(config, (min_opt,))
            end = parse_pair(config, (max_opt,))
            # Validate the corners.  If necessary reorganize them.
            # c1 = min point, c3 = max point
            #  c4 ---- c3
            #  |        |
            #  c1 ---- c2
            c1 = [min([s, e]) for s, e in zip(start, end)]
            c3 = [max([s, e]) for s, e in zip(start, end)]
            c2 = [c1[0], c3[1]]
            c4 = [c3[0], c1[1]]
            # Check for overlapping regions
            for j, (prev_c1, prev_c3) in enumerate(self.faulty_regions):
                prev_c2 = [prev_c1[0], prev_c3[1]]
                prev_c4 = [prev_c3[0], prev_c1[1]]
                # Validate that no existing corner is within the new region
                for coord in [prev_c1, prev_c2, prev_c3, prev_c4]:
                    if within(coord, c1, c3):
                        raise config.error(
                            "bed_mesh: Existing faulty_region_%d %s overlaps "
                            "added faulty_region_%d %s"
                            % (j+1, repr([prev_c1, prev_c3]), i, repr([c1, c3])))
                # Validate that no new corner is within an existing region
                for coord in [c1, c2, c3, c4]:
                    if within(coord, prev_c1, prev_c3):
                        raise config.error(
                            "bed_mesh: Added faulty_region_%d %s overlaps "
                            "existing faulty_region_%d %s"
                            % (i, repr([c1, c3]), j+1, repr([prev_c1, prev_c3])))
            self.faulty_regions.append((c1, c3))
        self._verify_algorithm(config.error)
    def _verify_algorithm(self, error):
        params = self.mesh_config
        x_pps = params['mesh_x_pps']
        y_pps = params['mesh_y_pps']
        if params['algo'] not in self.ALGOS:
            raise error(
                "bed_mesh: Unknown algorithm <%s>"
                % (self.mesh_config['algo']))
        # Check the algorithm against the current configuration
        max_probe_cnt = max(params['x_count'], params['y_count'])
        min_probe_cnt = min(params['x_count'], params['y_count'])
        if max(x_pps, y_pps) == 0:
            # Interpolation disabled
            self.mesh_config['algo'] = 'direct'
        elif params['algo'] == 'lagrange' and max_probe_cnt > 6:
            # Lagrange interpolation tends to oscillate when using more
            # than 6 samples
            raise error(
                "bed_mesh: cannot exceed a probe_count of 6 when using "
                "lagrange interpolation. Configured Probe Count: %d, %d" %
                (self.mesh_config['x_count'], self.mesh_config['y_count']))
        elif params['algo'] == 'bicubic' and min_probe_cnt < 4:
            if max_probe_cnt > 6:
                raise error(
                    "bed_mesh: invalid probe_count option when using bicubic "
                    "interpolation.  Combination of 3 points on one axis with "
                    "more than 6 on another is not permitted. "
                    "Configured Probe Count: %d, %d" %
                    (self.mesh_config['x_count'], self.mesh_config['y_count']))
            else:
                logging.info(
                    "bed_mesh: bicubic interpolation with a probe_count of "
                    "less than 4 points detected.  Forcing lagrange "
                    "interpolation. Configured Probe Count: %d, %d" %
                    (self.mesh_config['x_count'], self.mesh_config['y_count']))
                params['algo'] = 'lagrange'
    def update_config(self, gcmd):
        # reset default configuration
        self.radius = self.orig_config['radius']
        self.origin = self.orig_config['origin']
        self.relative_reference_index = self.orig_config['rri']
        self.mesh_min = self.orig_config['mesh_min']
        self.mesh_max = self.orig_config['mesh_max']
        for key in list(self.mesh_config.keys()):
            self.mesh_config[key] = self.orig_config[key]

        params = gcmd.get_command_parameters()
        need_cfg_update = False
        if 'RELATIVE_REFERENCE_INDEX' in params:
            self.relative_reference_index = gcmd.get_int(
                'RELATIVE_REFERENCE_INDEX')
            if self.relative_reference_index < 0:
                self.relative_reference_index = None
            need_cfg_update = True
        if self.radius is not None:
            if "MESH_RADIUS" in params:
                self.radius = gcmd.get_float("MESH_RADIUS")
                self.radius = math.floor(self.radius * 10) / 10
                self.mesh_min = (-self.radius, -self.radius)
                self.mesh_max = (self.radius, self.radius)
                need_cfg_update = True
            if "MESH_ORIGIN" in params:
                self.origin = parse_pair(gcmd, ('MESH_ORIGIN',))
                need_cfg_update = True
            if "ROUND_PROBE_COUNT" in params:
                cnt = gcmd.get_int('ROUND_PROBE_COUNT', minval=3)
                self.mesh_config['x_count'] = cnt
                self.mesh_config['y_count'] = cnt
                need_cfg_update = True
        else:
            if "MESH_MIN" in params:
                self.mesh_min = parse_pair(gcmd, ('MESH_MIN',))
                need_cfg_update = True
            if "MESH_MAX" in params:
                self.mesh_max = parse_pair(gcmd, ('MESH_MAX',))
                need_cfg_update = True
            if "PROBE_COUNT" in params:
                x_cnt, y_cnt = parse_pair(
                    gcmd, ('PROBE_COUNT',), check=False, cast=int, minval=3)
                self.mesh_config['x_count'] = x_cnt
                self.mesh_config['y_count'] = y_cnt
                need_cfg_update = True

        if "ALGORITHM" in params:
            self.mesh_config['algo'] = gcmd.get('ALGORITHM').strip().lower()
            need_cfg_update = True

        if need_cfg_update:
            self._verify_algorithm(gcmd.error)
            self._generate_points(gcmd.error)
            gcmd.respond_info("Generating new points...")
            self.print_generated_points(gcmd.respond_info)
            pts = self._get_adjusted_points()
            self.probe_helper.update_probe_points(pts, 3)
            msg = "relative_reference_index: %s\n" % \
                (self.relative_reference_index)
            msg += "\n".join(["%s: %s" % (k, v) for k, v
                              in self.mesh_config.items()])
            logging.info("Updated Mesh Configuration:\n" + msg)
        else:
            self.points = self.orig_points
            pts = self._get_adjusted_points()
            self.probe_helper.update_probe_points(pts, 3)
    def _get_adjusted_points(self):
        if not self.substituted_indices:
            return self.points
        adj_pts = []
        last_index = 0
        for i, pts in self.substituted_indices.items():
            adj_pts.extend(self.points[last_index:i])
            adj_pts.extend(pts)
            # Add one to the last index to skip the point
            # we are replacing
            last_index = i + 1
        adj_pts.extend(self.points[last_index:])
        return adj_pts
    cmd_BED_MESH_CALIBRATE_help = "Perform Mesh Bed Leveling"
    def cmd_BED_MESH_CALIBRATE(self, gcmd):
        self.bedmesh.set_mesh(None)
        self.update_config(gcmd)
        self.probe_helper.start_probe(gcmd)
    def probe_finalize(self, offsets, positions):
        x_offset, y_offset, z_offset = offsets
        positions = [[round(p[0], 2), round(p[1], 2), p[2]]
                     for p in positions]
        params = dict(self.mesh_config)
        params['min_x'] = min(positions, key=lambda p: p[0])[0] + x_offset
        params['max_x'] = max(positions, key=lambda p: p[0])[0] + x_offset
        params['min_y'] = min(positions, key=lambda p: p[1])[1] + y_offset
        params['max_y'] = max(positions, key=lambda p: p[1])[1] + y_offset
        x_cnt = params['x_count']
        y_cnt = params['y_count']

        if self.substituted_indices:
            # Replace substituted points with the original generated
            # point.  Its Z Value is the average probed Z of the
            # substituted points.
            corrected_pts = []
            idx_offset = 0
            start_idx = 0
            for i, pts in self.substituted_indices.items():
                fpt = [p - o for p, o in zip(self.points[i], offsets[:2])]
                # offset the index to account for additional samples
                idx = i + idx_offset
                # Add "normal" points
                corrected_pts.extend(positions[start_idx:idx])
                avg_z = sum([p[2] for p in positions[idx:idx+len(pts)]]) \
                    / len(pts)
                idx_offset += len(pts) - 1
                start_idx = idx + len(pts)
                fpt.append(avg_z)
                logging.info(
                    "bed_mesh: Replacing value at faulty index %d"
                    " (%.4f, %.4f): avg value = %.6f, avg w/ z_offset = %.6f"
                    % (i, fpt[0], fpt[1], avg_z, avg_z - z_offset))
                corrected_pts.append(fpt)
            corrected_pts.extend(positions[start_idx:])
            # validate corrected positions
            if len(self.points) != len(corrected_pts):
                self._dump_points(positions, corrected_pts, offsets)
                raise self.gcode.error(
                    "bed_mesh: invalid position list size, "
                    "generated count: %d, probed count: %d"
                    % (len(self.points), len(corrected_pts)))
            for gen_pt, probed in zip(self.points, corrected_pts):
                off_pt = [p - o for p, o in zip(gen_pt, offsets[:2])]
                if not isclose(off_pt[0], probed[0], abs_tol=.1) or \
                        not isclose(off_pt[1], probed[1], abs_tol=.1):
                    self._dump_points(positions, corrected_pts, offsets)
                    raise self.gcode.error(
                        "bed_mesh: point mismatch, orig = (%.2f, %.2f)"
                        ", probed = (%.2f, %.2f)"
                        % (off_pt[0], off_pt[1], probed[0], probed[1]))
            positions = corrected_pts

        if self.relative_reference_index is not None:
            # zero out probe z offset and
            # set offset relative to reference index
            z_offset = positions[self.relative_reference_index][2]

        probed_matrix = []
        row = []
        prev_pos = positions[0]
        for pos in positions:
            if not isclose(pos[1], prev_pos[1], abs_tol=.1):
                # y has changed, append row and start new
                probed_matrix.append(row)
                row = []
            if pos[0] > prev_pos[0]:
                # probed in the positive direction
                row.append(pos[2] - z_offset)
            else:
                # probed in the negative direction
                row.insert(0, pos[2] - z_offset)
            prev_pos = pos
        # append last row
        probed_matrix.append(row)

        # make sure the y-axis is the correct length
        if len(probed_matrix) != y_cnt:
            raise self.gcode.error(
                ("bed_mesh: Invalid y-axis table length\n"
                 "Probed table length: %d Probed Table:\n%s") %
                (len(probed_matrix), str(probed_matrix)))

        if self.radius is not None:
            # round bed, extrapolate probed values to create a square mesh
            for row in probed_matrix:
                row_size = len(row)
                if not row_size & 1:
                    # an even number of points in a row shouldn't be possible
                    msg = "bed_mesh: incorrect number of points sampled on X\n"
                    msg += "Probed Table:\n"
                    msg += str(probed_matrix)
                    raise self.gcode.error(msg)
                buf_cnt = (x_cnt - row_size) // 2
                if buf_cnt == 0:
                    continue
                left_buffer = [row[0]] * buf_cnt
                right_buffer = [row[row_size-1]] * buf_cnt
                row[0:0] = left_buffer
                row.extend(right_buffer)

        #  make sure that the x-axis is the correct length
        for row in probed_matrix:
            if len(row) != x_cnt:
                raise self.gcode.error(
                    ("bed_mesh: invalid x-axis table length\n"
                        "Probed table length: %d Probed Table:\n%s") %
                    (len(probed_matrix), str(probed_matrix)))

        z_mesh = ZMesh(params)
        try:
            z_mesh.build_mesh(probed_matrix)
        except BedMeshError as e:
            raise self.gcode.error(str(e))
        self.bedmesh.set_mesh(z_mesh)
        self.gcode.respond_info("Mesh Bed Leveling Complete")
        self.bedmesh.save_profile("default")
    def _dump_points(self, probed_pts, corrected_pts, offsets):
        # logs generated points with offset applied, points received
        # from the finalize callback, and the list of corrected points
        max_len = max([len(self.points), len(probed_pts), len(corrected_pts)])
        logging.info(
            "bed_mesh: calibration point dump\nIndex | %-17s| %-25s|"
            " Corrected Point" % ("Generated Point", "Probed Point"))
        for i in list(range(max_len)):
            gen_pt = probed_pt = corr_pt = ""
            if i < len(self.points):
                off_pt = [p - o for p, o in zip(self.points[i], offsets[:2])]
                gen_pt = "(%.2f, %.2f)" % tuple(off_pt)
            if i < len(probed_pts):
                probed_pt = "(%.2f, %.2f, %.4f)" % tuple(probed_pts[i])
            if i < len(corrected_pts):
                corr_pt = "(%.2f, %.2f, %.4f)" % tuple(corrected_pts[i])
            logging.info(
                "  %-4d| %-17s| %-25s| %s" % (i, gen_pt, probed_pt, corr_pt))


class MoveSplitter:
    def __init__(self, config, gcode):
        self.split_delta_z = config.getfloat(
            'split_delta_z', .025, minval=0.01)
        self.move_check_distance = config.getfloat(
            'move_check_distance', 5., minval=3.)
        self.z_mesh = None
        self.fade_offset = 0.
        self.gcode = gcode
    def initialize(self, mesh, fade_offset):
        self.z_mesh = mesh
        self.fade_offset = fade_offset
    def build_move(self, prev_pos, next_pos, factor):
        self.prev_pos = tuple(prev_pos)
        self.next_pos = tuple(next_pos)
        self.current_pos = list(prev_pos)
        self.z_factor = factor
        self.z_offset = self._calc_z_offset(prev_pos)
        self.traverse_complete = False
        self.distance_checked = 0.
        axes_d = [self.next_pos[i] - self.prev_pos[i] for i in range(4)]
        self.total_move_length = math.sqrt(sum([d*d for d in axes_d[:3]]))
        self.axis_move = [not isclose(d, 0., abs_tol=1e-10) for d in axes_d]
    def _calc_z_offset(self, pos):
        z = self.z_mesh.calc_z(pos[0], pos[1])
        offset = self.fade_offset
        return self.z_factor * (z - offset) + offset
    def _set_next_move(self, distance_from_prev):
        t = distance_from_prev / self.total_move_length
        if t > 1. or t < 0.:
            raise self.gcode.error(
                "bed_mesh: Slice distance is negative "
                "or greater than entire move length")
        for i in range(4):
            if self.axis_move[i]:
                self.current_pos[i] = lerp(
                    t, self.prev_pos[i], self.next_pos[i])
    def split(self):
        if not self.traverse_complete:
            if self.axis_move[0] or self.axis_move[1]:
                # X and/or Y axis move, traverse if necessary
                while self.distance_checked + self.move_check_distance \
                        < self.total_move_length:
                    self.distance_checked += self.move_check_distance
                    self._set_next_move(self.distance_checked)
                    next_z = self._calc_z_offset(self.current_pos)
                    if abs(next_z - self.z_offset) >= self.split_delta_z:
                        self.z_offset = next_z
                        return self.current_pos[0], self.current_pos[1], \
                            self.current_pos[2] + self.z_offset, \
                            self.current_pos[3]
            # end of move reached
            self.current_pos[:] = self.next_pos
            self.z_offset = self._calc_z_offset(self.current_pos)
            # Its okay to add Z-Offset to the final move, since it will not be
            # used again.
            self.current_pos[2] += self.z_offset
            self.traverse_complete = True
            return self.current_pos
        else:
            # Traverse complete
            return None


class ZMesh:
    def __init__(self, params):
        self.probed_matrix = self.mesh_matrix = None
        self.mesh_params = params
        self.avg_z = 0.
        self.mesh_offsets = [0., 0.]
        logging.debug('bed_mesh: probe/mesh parameters:')
        for key, value in self.mesh_params.items():
            logging.debug("%s :  %s" % (key, value))
        self.mesh_x_min = params['min_x']
        self.mesh_x_max = params['max_x']
        self.mesh_y_min = params['min_y']
        self.mesh_y_max = params['max_y']
        logging.debug(
            "bed_mesh: Mesh Min: (%.2f,%.2f) Mesh Max: (%.2f,%.2f)"
            % (self.mesh_x_min, self.mesh_y_min,
               self.mesh_x_max, self.mesh_y_max))
        # Set the interpolation algorithm
        interpolation_algos = {
            'lagrange': self._sample_lagrange,
            'bicubic': self._sample_bicubic,
            'direct': self._sample_direct
        }
        self._sample = interpolation_algos.get(params['algo'])
        # Number of points to interpolate per segment
        mesh_x_pps = params['mesh_x_pps']
        mesh_y_pps = params['mesh_y_pps']
        px_cnt = params['x_count']
        py_cnt = params['y_count']
        self.mesh_x_count = (px_cnt - 1) * mesh_x_pps + px_cnt
        self.mesh_y_count = (py_cnt - 1) * mesh_y_pps + py_cnt
        self.x_mult = mesh_x_pps + 1
        self.y_mult = mesh_y_pps + 1
        logging.debug("bed_mesh: Mesh grid size - X:%d, Y:%d"
                      % (self.mesh_x_count, self.mesh_y_count))
        self.mesh_x_dist = (self.mesh_x_max - self.mesh_x_min) / \
                           (self.mesh_x_count - 1)
        self.mesh_y_dist = (self.mesh_y_max - self.mesh_y_min) / \
                           (self.mesh_y_count - 1)
    def get_mesh_matrix(self):
        if self.mesh_matrix is not None:
            return [[round(z, 6) for z in line]
                    for line in self.mesh_matrix]
        return [[]]
    def get_probed_matrix(self):
        if self.probed_matrix is not None:
            return [[round(z, 6) for z in line]
                    for line in self.probed_matrix]
        return [[]]
    def get_mesh_params(self):
        return self.mesh_params
    def print_probed_matrix(self, print_func):
        if self.probed_matrix is not None:
            msg = "Mesh Leveling Probed Z positions:\n"
            for line in self.probed_matrix:
                for x in line:
                    msg += " %f" % x
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: bed has not been probed")
    def print_mesh(self, print_func, move_z=None):
        matrix = self.get_mesh_matrix()
        if matrix is not None:
            msg = "Mesh X,Y: %d,%d\n" % (self.mesh_x_count, self.mesh_y_count)
            if move_z is not None:
                msg += "Search Height: %d\n" % (move_z)
            msg += "Mesh Offsets: X=%.4f, Y=%.4f\n" % (
                self.mesh_offsets[0], self.mesh_offsets[1])
            msg += "Mesh Average: %.2f\n" % (self.avg_z)
            rng = self.get_z_range()
            msg += "Mesh Range: min=%.4f max=%.4f\n" % (rng[0], rng[1])
            msg += "Interpolation Algorithm: %s\n" \
                   % (self.mesh_params['algo'])
            msg += "Measured points:\n"
            for y_line in range(self.mesh_y_count - 1, -1, -1):
                for z in matrix[y_line]:
                    msg += "  %f" % (z)
                msg += "\n"
            print_func(msg)
        else:
            print_func("bed_mesh: Z Mesh not generated")
    def build_mesh(self, z_matrix):
        self.probed_matrix = z_matrix
        self._sample(z_matrix)
        self.avg_z = (sum([sum(x) for x in self.mesh_matrix]) /
                      sum([len(x) for x in self.mesh_matrix]))
        # Round average to the nearest 100th.  This
        # should produce an offset that is divisible by common
        # z step distances
        self.avg_z = round(self.avg_z, 2)
        self.print_mesh(logging.debug)
    def set_mesh_offsets(self, offsets):
        for i, o in enumerate(offsets):
            if o is not None:
                self.mesh_offsets[i] = o
    def get_x_coordinate(self, index):
        return self.mesh_x_min + self.mesh_x_dist * index
    def get_y_coordinate(self, index):
        return self.mesh_y_min + self.mesh_y_dist * index
    def calc_z(self, x, y):
        if self.mesh_matrix is not None:
            tbl = self.mesh_matrix
            tx, xidx = self._get_linear_index(x + self.mesh_offsets[0], 0)
            ty, yidx = self._get_linear_index(y + self.mesh_offsets[1], 1)
            z0 = lerp(tx, tbl[yidx][xidx], tbl[yidx][xidx+1])
            z1 = lerp(tx, tbl[yidx+1][xidx], tbl[yidx+1][xidx+1])
            return lerp(ty, z0, z1)
        else:
            # No mesh table generated, no z-adjustment
            return 0.
    def get_z_range(self):
        if self.mesh_matrix is not None:
            mesh_min = min([min(x) for x in self.mesh_matrix])
            mesh_max = max([max(x) for x in self.mesh_matrix])
            return mesh_min, mesh_max
        else:
            return 0., 0.
    def _get_linear_index(self, coord, axis):
        if axis == 0:
            # X-axis
            mesh_min = self.mesh_x_min
            mesh_cnt = self.mesh_x_count
            mesh_dist = self.mesh_x_dist
            cfunc = self.get_x_coordinate
        else:
            # Y-axis
            mesh_min = self.mesh_y_min
            mesh_cnt = self.mesh_y_count
            mesh_dist = self.mesh_y_dist
            cfunc = self.get_y_coordinate
        t = 0.
        idx = int(math.floor((coord - mesh_min) / mesh_dist))
        idx = constrain(idx, 0, mesh_cnt - 2)
        t = (coord - cfunc(idx)) / mesh_dist
        return constrain(t, 0., 1.), idx
    def _sample_direct(self, z_matrix):
        self.mesh_matrix = z_matrix
    def _sample_lagrange(self, z_matrix):
        x_mult = self.x_mult
        y_mult = self.y_mult
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j//y_mult][i//x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        xpts, ypts = self._get_lagrange_coords()
        # Interpolate X coordinates
        for i in range(self.mesh_y_count):
            # only interpolate X-rows that have probed coordinates
            if i % y_mult != 0:
                continue
            for j in range(self.mesh_x_count):
                if j % x_mult == 0:
                    continue
                x = self.get_x_coordinate(j)
                self.mesh_matrix[i][j] = self._calc_lagrange(xpts, x, i, 0)
        # Interpolate Y coordinates
        for i in range(self.mesh_x_count):
            for j in range(self.mesh_y_count):
                if j % y_mult == 0:
                    continue
                y = self.get_y_coordinate(j)
                self.mesh_matrix[j][i] = self._calc_lagrange(ypts, y, i, 1)
    def _get_lagrange_coords(self):
        xpts = []
        ypts = []
        for i in range(self.mesh_params['x_count']):
            xpts.append(self.get_x_coordinate(i * self.x_mult))
        for j in range(self.mesh_params['y_count']):
            ypts.append(self.get_y_coordinate(j * self.y_mult))
        return xpts, ypts
    def _calc_lagrange(self, lpts, c, vec, axis=0):
        pt_cnt = len(lpts)
        total = 0.
        for i in range(pt_cnt):
            n = 1.
            d = 1.
            for j in range(pt_cnt):
                if j == i:
                    continue
                n *= (c - lpts[j])
                d *= (lpts[i] - lpts[j])
            if axis == 0:
                # Calc X-Axis
                z = self.mesh_matrix[vec][i*self.x_mult]
            else:
                # Calc Y-Axis
                z = self.mesh_matrix[i*self.y_mult][vec]
            total += z * n / d
        return total
    def _sample_bicubic(self, z_matrix):
        # should work for any number of probe points above 3x3
        x_mult = self.x_mult
        y_mult = self.y_mult
        c = self.mesh_params['tension']
        self.mesh_matrix = \
            [[0. if ((i % x_mult) or (j % y_mult))
             else z_matrix[j//y_mult][i//x_mult]
             for i in range(self.mesh_x_count)]
             for j in range(self.mesh_y_count)]
        # Interpolate X values
        for y in range(self.mesh_y_count):
            if y % y_mult != 0:
                continue
            for x in range(self.mesh_x_count):
                if x % x_mult == 0:
                    continue
                pts = self._get_x_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
        # Interpolate Y values
        for x in range(self.mesh_x_count):
            for y in range(self.mesh_y_count):
                if y % y_mult == 0:
                    continue
                pts = self._get_y_ctl_pts(x, y)
                self.mesh_matrix[y][x] = self._cardinal_spline(pts, c)
    def _get_x_ctl_pts(self, x, y):
        # Fetch control points and t for a X value in the mesh
        x_mult = self.x_mult
        x_row = self.mesh_matrix[y]
        last_pt = self.mesh_x_count - 1 - x_mult
        if x < x_mult:
            p0 = p1 = x_row[0]
            p2 = x_row[x_mult]
            p3 = x_row[2*x_mult]
            t = x / float(x_mult)
        elif x > last_pt:
            p0 = x_row[last_pt - x_mult]
            p1 = x_row[last_pt]
            p2 = p3 = x_row[last_pt + x_mult]
            t = (x - last_pt) / float(x_mult)
        else:
            found = False
            for i in range(x_mult, last_pt, x_mult):
                if x > i and x < (i + x_mult):
                    p0 = x_row[i - x_mult]
                    p1 = x_row[i]
                    p2 = x_row[i + x_mult]
                    p3 = x_row[i + 2*x_mult]
                    t = (x - i) / float(x_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding x control points")
        return p0, p1, p2, p3, t
    def _get_y_ctl_pts(self, x, y):
        # Fetch control points and t for a Y value in the mesh
        y_mult = self.y_mult
        last_pt = self.mesh_y_count - 1 - y_mult
        y_col = self.mesh_matrix
        if y < y_mult:
            p0 = p1 = y_col[0][x]
            p2 = y_col[y_mult][x]
            p3 = y_col[2*y_mult][x]
            t = y / float(y_mult)
        elif y > last_pt:
            p0 = y_col[last_pt - y_mult][x]
            p1 = y_col[last_pt][x]
            p2 = p3 = y_col[last_pt + y_mult][x]
            t = (y - last_pt) / float(y_mult)
        else:
            found = False
            for i in range(y_mult, last_pt, y_mult):
                if y > i and y < (i + y_mult):
                    p0 = y_col[i - y_mult][x]
                    p1 = y_col[i][x]
                    p2 = y_col[i + y_mult][x]
                    p3 = y_col[i + 2*y_mult][x]
                    t = (y - i) / float(y_mult)
                    found = True
                    break
            if not found:
                raise BedMeshError(
                    "bed_mesh: Error finding y control points")
        return p0, p1, p2, p3, t
    def _cardinal_spline(self, p, tension):
        t = p[4]
        t2 = t*t
        t3 = t2*t
        m1 = tension * (p[2] - p[0])
        m2 = tension * (p[3] - p[1])
        a = p[1] * (2*t3 - 3*t2 + 1)
        b = p[2] * (-2*t3 + 3*t2)
        c = m1 * (t3 - 2*t2 + t)
        d = m2 * (t3 - t2)
        return a + b + c + d


class ProfileManager:
    def __init__(self, config, bedmesh):
        self.name = config.get_name()
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.bedmesh = bedmesh
        self.profiles = {}
        self.current_profile = ""
        self.incompatible_profiles = []
        # Fetch stored profiles from Config
        stored_profs = config.get_prefix_sections(self.name)
        stored_profs = [s for s in stored_profs
                        if s.get_name() != self.name]
        for profile in stored_profs:
            name = profile.get_name().split(' ', 1)[1]
            version = profile.getint('version', 0)
            if version != PROFILE_VERSION:
                logging.info(
                    "bed_mesh: Profile [%s] not compatible with this version\n"
                    "of bed_mesh.  Profile Version: %d Current Version: %d "
                    % (name, version, PROFILE_VERSION))
                self.incompatible_profiles.append(name)
                continue
            self.profiles[name] = {}
            z_values = profile.get('points').split('\n')
            self.profiles[name]['points'] = \
                [[float(pt.strip()) for pt in line.split(',')]
                    for line in z_values if line.strip()]
            self.profiles[name]['mesh_params'] = params = \
                collections.OrderedDict()
            for key, t in PROFILE_OPTIONS.items():
                if t is int:
                    params[key] = profile.getint(key)
                elif t is float:
                    params[key] = profile.getfloat(key)
                elif t is str:
                    params[key] = profile.get(key)
        # Register GCode
        self.gcode.register_command(
            'BED_MESH_PROFILE', self.cmd_BED_MESH_PROFILE,
            desc=self.cmd_BED_MESH_PROFILE_help)
    def initialize(self):
        self._check_incompatible_profiles()
        if "default" in self.profiles:
            self.load_profile("default")
    def get_current_profile(self):
        return self.current_profile
    def _check_incompatible_profiles(self):
        if self.incompatible_profiles:
            configfile = self.printer.lookup_object('configfile')
            for profile in self.incompatible_profiles:
                configfile.remove_section('bed_mesh ' + profile)
            self.gcode.respond_info(
                "The following incompatible profiles have been detected\n"
                "and are scheduled for removal:\n%s\n"
                "The SAVE_CONFIG command will update the printer config\n"
                "file and restart the printer" %
                (('\n').join(self.incompatible_profiles)))
    def save_profile(self, prof_name):
        z_mesh = self.bedmesh.get_mesh()
        if z_mesh is None:
            self.gcode.respond_info(
                "Unable to save to profile [%s], the bed has not been probed"
                % (prof_name))
            return
        probed_matrix = z_mesh.get_probed_matrix()
        mesh_params = z_mesh.get_mesh_params()
        configfile = self.printer.lookup_object('configfile')
        cfg_name = self.name + " " + prof_name
        # set params
        z_values = ""
        for line in probed_matrix:
            z_values += "\n  "
            for p in line:
                z_values += "%.6f, " % p
            z_values = z_values[:-2]
        configfile.set(cfg_name, 'version', PROFILE_VERSION)
        configfile.set(cfg_name, 'points', z_values)
        for key, value in mesh_params.items():
            configfile.set(cfg_name, key, value)
        # save copy in local storage
        self.profiles[prof_name] = profile = {}
        profile['points'] = probed_matrix
        profile['mesh_params'] = collections.OrderedDict(mesh_params)
        self.current_profile = prof_name
        self.gcode.respond_info(
            "Bed Mesh state has been saved to profile [%s]\n"
            "for the current session.  The SAVE_CONFIG command will\n"
            "update the printer config file and restart the printer."
            % (prof_name))
    def load_profile(self, prof_name):
        profile = self.profiles.get(prof_name, None)
        if profile is None:
            raise self.gcode.error(
                "bed_mesh: Unknown profile [%s]" % prof_name)
        probed_matrix = profile['points']
        mesh_params = profile['mesh_params']
        z_mesh = ZMesh(mesh_params)
        try:
            z_mesh.build_mesh(probed_matrix)
        except BedMeshError as e:
            raise self.gcode.error(str(e))
        self.current_profile = prof_name
        self.bedmesh.set_mesh(z_mesh)
    def remove_profile(self, prof_name):
        if prof_name in self.profiles:
            configfile = self.printer.lookup_object('configfile')
            configfile.remove_section('bed_mesh ' + prof_name)
            del self.profiles[prof_name]
            self.gcode.respond_info(
                "Profile [%s] removed from storage for this session.\n"
                "The SAVE_CONFIG command will update the printer\n"
                "configuration and restart the printer" % (prof_name))
        else:
            self.gcode.respond_info(
                "No profile named [%s] to remove" % (prof_name))
    cmd_BED_MESH_PROFILE_help = "Bed Mesh Persistent Storage management"
    def cmd_BED_MESH_PROFILE(self, gcmd):
        options = collections.OrderedDict({
            'LOAD': self.load_profile,
            'SAVE': self.save_profile,
            'REMOVE': self.remove_profile
        })
        for key in options:
            name = gcmd.get(key, None)
            if name is not None:
                if name == "default" and key == 'SAVE':
                    gcmd.respond_info(
                        "Profile 'default' is reserved, please choose"
                        " another profile name.")
                else:
                    options[key](name)
                return
        gcmd.respond_info("Invalid syntax '%s'" % (gcmd.get_commandline(),))


def load_config(config):
    return BedMesh(config)
