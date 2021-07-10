import logging, math

SUBDIV_ACCURACY = 0.01
CIRCLES_ACCURACY = 0.05
SUBDIV_SIZE = 0.5

class SkewAutoCalibration:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.z_position = config.getfloat("z_position", 2.0)
        self.z_hop = config.getfloat("z_hop", 2.0)
        self.radius = config.getfloat("radius", 6, above=.0, below=20.0)
        self.iterations = config.getint("iterations", 4, minval=2, maxval=16)
        self.speed = config.getfloat('speed', 50., above=0.)
        self.z_speed = config.getfloat('z_speed', 5., above=0.)
        self.query_endstops = self.printer.load_object(config, 'query_endstops')
        gantry_corners = config.get('gantry_corners').split('\n')
        try:
            gantry_corners = [line.split(',', 1)
                           for line in gantry_corners if line.strip()]
            self.gantry_corners = [(float(zp[0].strip()), float(zp[1].strip()))
                                for zp in gantry_corners]
        except:
            raise config.error("Unable to parse gantry_corners in %s" % (
                config.get_name()))
        if len(self.gantry_corners) != 4:
            raise config.error(
                "skew_auto_calibration requires exactly four gantry_corners")
        # Register SKEW_AUTO_CALIBRATION command
        self.gcode = self.printer.lookup_object('gcode')
        self.gcode.register_command(
            'SKEW_AUTO_CALIBRATION', self.cmd_SKEW_AUTO_CALIBRATION,
            desc=self.cmd_SKEW_AUTO_CALIBRATION_help)
    cmd_SKEW_AUTO_CALIBRATION_help = (
        "...")
    def cmd_SKEW_AUTO_CALIBRATION(self, gcmd):
        self._ensure_homed()

        corners = self._find_gantry_corners(gcmd)
        if len(corners) != 4:
            gcmd.respond_info("Not enough points found")
            return

        # A, B, C, D
        ac = self._vect_len2(corners[0], corners[2])
        bd = self._vect_len2(corners[1], corners[3])
        ad = self._vect_len2(corners[0], corners[3])
        gcmd.respond_info("SET_SKEW XY=%.3f,%.3f,%.3f" % (ac, bd, ad))

    def _ensure_homed(self):
        self.gcode.run_script_from_command("G28")

        toolhead = self.printer.lookup_object('toolhead')
        curtime = self.printer.get_reactor().monotonic()
        if 'xyz' not in toolhead.get_status(curtime)['homed_axes']:
            raise self.printer.command_error("Must home before calibration")

    def _find_gantry_corners(self, gcmd):
        corners = []
        offset = [0, 0]

        for corner_pt in self.gantry_corners:
            # we apply an offset from previous run
            # since mostly the same shift will be on a whole bed
            test_pt = self._vect_add(corner_pt, offset)
            center_pt = self._find_circle_center_n(gcmd, test_pt)
            if not center_pt:
                break

            gcmd.respond_info("%s: Found at %s" % (
                self._vect_round(corner_pt), self._vect_round(center_pt)))
            corners.append(center_pt)
            offset = self._vect_sub(center_pt, corner_pt)

        return corners

    def _find_circle_center_n(self, gcmd, center):
        pt = center

        # iterate to find a closest match in a subsequent runs
        for i in range(self.iterations):
            pt, radius, accuracy = self._find_circle_center(gcmd, pt)
            if not pt:
                gcmd.respond_info("%s: Iteration %d: circle not found" % (
                    self._vect_round(center), i
                ))
                break

            gcmd.respond_info("%s: Iteration %d: %s / %.3f / %.3f" % (
                self._vect_round(center), i, self._vect_round(pt),
                radius, accuracy))

            if accuracy < CIRCLES_ACCURACY:
                return pt

        return None

    def _find_circle_center(self, gcmd, center):
        edges = self._find_edges(gcmd, center)
        if len(edges)<3:
            gcmd.respond_info("Too few edges (%d)" % (len(edges)))
            return None, None, None

        best_circle, best_radius, best_length, best_accuracy = None, None, 0, 0

        # find a circle with most spread edges
        for i in range(len(edges)-1):
            e1 = edges[i]
            e2 = edges[(i+1)%len(edges)]
            e3 = edges[(i+2)%len(edges)]
            length = self._vect_len2(e1, e2) + \
                self._vect_len2(e2, e3) + \
                self._vect_len2(e1, e3)
            if length < best_length:
                continue

            best_circle, best_radius = self._find_circle(e1, e2, e3)
            best_length = length
            best_accuracy = self._vect_len2(center, best_circle)

        return best_circle, best_radius, best_accuracy

    def _find_edges(self, gcmd, p1):
        # we expect that at this point endstop will engage
        if not self._endstop_state_at(p1):
            gcmd.respond_info("%s not found" % (self._vect_round(p1)))
            return []

        found_pts = []
        dirs = [-1,0],[0,1],[1,0],[0,-1] # move by circle
        n = int(math.ceil(self.radius/SUBDIV_SIZE))

        for dir_pt in dirs:
            p2 = self._vect_add(p1, self._vect_scale(dir_pt, self.radius))
            edge_pt = self._find_edge(p1, p2, n)
            if edge_pt:
                found_pts.append(edge_pt)
            else:
                gcmd.respond_info("edge not found for %s-%s" % (
                    self._vect_round(p1), self._vect_round(p2)))

        return found_pts

    def _find_edge(self, p1, p2, n):
        if self._vect_len2(p1, p2) < SUBDIV_ACCURACY or n < 2:
            return p1

        prev = p1

        for i in range(n):
            t = float(i+1) / n # we already checked x0/y0
            cur = self._vect_interpolate(p1, p2, t)

            # if we hit edge, subdiv or return current value
            # return always a last know position that engaged endstop
            if not self._endstop_state_at(cur):
                result = self._find_edge(prev, cur, 8)
                return result or prev

            prev = cur

        return None

    def _endstop_state_at(self, pos):
        # check endstop with a z-hop to increase an accuracy
        toolhead = self.printer.lookup_object('toolhead')
        toolhead.manual_move(
            [None, None, self.z_position + self.z_hop], self.z_speed)
        toolhead.manual_move(pos, self.speed)
        toolhead.manual_move([None, None, self.z_position], self.z_speed)
        #TODO: is this needed?
        #toolhead.wait_moves()

        return self.query_endstops.request_status('z')

    def _vect_add(self, p1, p2):
        return p1[0]+p2[0], p1[1]+p2[1]

    def _vect_sub(self, p1, p2):
        return p1[0]-p2[0], p1[1]-p2[1]

    def _vect_scale(self, p, f):
        return p[0]*f, p[1]*f

    def _vect_len(self, p):
        return math.sqrt(p[0]**2 + p[1]**2)

    def _vect_len2(self, p1, p2):
        return self._vect_len(self._vect_sub(p1, p2))

    def _vect_interpolate(self, p1, p2, t):
        return self._vect_add(
            self._vect_scale(p1, 1-t),
            self._vect_scale(p2, t),
        )

    def _vect_round(self, p, d = 3):
        return round(p[0], d), round(p[1], d)

    def _find_circle(self, p1, p2, p3):
        """
        From: https://stackoverflow.com/a/50974391
        Returns the center and radius of the circle passing the given 3 points.
        In case the 3 points form a line, returns (None, infinity).
        """
        temp = p2[0] * p2[0] + p2[1] * p2[1]
        bc = (p1[0] * p1[0] + p1[1] * p1[1] - temp) / 2
        cd = (temp - p3[0] * p3[0] - p3[1] * p3[1]) / 2
        det = (p1[0] - p2[0]) * (p2[1] - p3[1]) - \
              (p2[0] - p3[0]) * (p1[1] - p2[1])

        if abs(det) < 1.0e-6:
            return None, None

        # Center of circle
        cx = (bc*(p2[1] - p3[1]) - cd*(p1[1] - p2[1])) / det
        cy = ((p1[0] - p2[0]) * cd - (p2[0] - p3[0]) * bc) / det

        radius = math.sqrt((cx - p1[0])**2 + (cy - p1[1])**2)
        return (cx, cy), radius

def load_config(config):
    return SkewAutoCalibration(config)
