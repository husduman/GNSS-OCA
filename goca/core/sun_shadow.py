import numpy as np


class SunEarthGeometry:
    """
    Sun–Earth geometry and eclipse utilities.

    Contents:
      - High-precision Sun position (ECEF, ~1" accuracy)
      - Ray–ellipsoid shadow test for an ellipsoidal Earth (umbra/penumbra)
    """

    # ==========================================================
    #  Julian Date helper (Meeus)
    # ==========================================================
    @staticmethod
    def _datetime2jd(y, m, d):
        """
        Simple Julian Day calculator (Meeus).
        d: day + fractional day (örn. D + UT/24)
        """
        if m <= 2:
            y -= 1
            m += 12
        A = np.floor(y / 100.0)
        B = 2 - A + np.floor(A / 4.0)
        JD = (np.floor(365.25 * (y + 4716)) +
              np.floor(30.6001 * (m + 1)) +
              d + B - 1524.5)
        return JD

    # ==========================================================
    #  High-precision Sun position in ECEF (Meeus)
    # ==========================================================
    @staticmethod
    def sun_position_ecef_highprec(time_utc,
                                   UT1_UTC=0.0,
                                   polar=None,
                                   aEarth=6378.137):
        """
        High-accuracy Sun position in ECEF using a Python datetime input.

        Parameters
        ----------
        time_utc : datetime (naive or timezone-aware)
            UTC datetime of observation.
        UT1_UTC : float, optional
            UT1-UTC in seconds (default 0).
        polar : [xp, yp] arcsec, optional
            Polar motion values.
        aEarth : float, optional
            Earth equatorial radius (km).

        Returns
        -------
        sunECEF : ndarray(3,)
            Sun position in ECEF [km].
        """
        import datetime

        # --- ensure UTC ---
        if time_utc.tzinfo is not None:
            time_utc = time_utc.astimezone(datetime.timezone.utc).replace(tzinfo=None)

        # extract fields
        y = time_utc.year
        m = time_utc.month
        D = time_utc.day
        UT = (time_utc.hour +
              time_utc.minute / 60.0 +
              time_utc.second / 3600.0 +
              time_utc.microsecond / 3.6e9)

        AU = 1.495978707e8  # km
        DEG2RAD = np.pi / 180.0
        ARCSEC2RAD = np.pi / 648000.0
        TWOPI = 2.0 * np.pi

        # --- 1) Julian date ---
        d = D + UT / 24.0
        JD = SunEarthGeometry._datetime2jd(y, m, d)

        # --- 2) TT = UTC + 32.184s approximation ---
        JD_TT = JD + 32.184 / 86400.0
        T = (JD_TT - 2451545.0) / 36525.0

        # --- 3) Solar geometric parameters (Meeus) ---
        T2 = T * T
        T3 = T2 * T

        L0 = (280.46646 + 36000.76983 * T + 0.0003032 * T2) % 360.0
        M = (357.52911 + 35999.05029 * T - 0.0001537 * T2) % 360.0
        e = 0.016708634 - 0.000042037 * T - 0.0000001267 * T2

        Mr = M * DEG2RAD
        sinM = np.sin(Mr)
        sin2M = np.sin(2.0 * Mr)
        sin3M = np.sin(3.0 * Mr)

        C = ((1.914602 - 0.004817 * T - 0.000014 * T2) * sinM +
             (0.019993 - 0.000101 * T) * sin2M +
             0.000289 * sin3M)

        trueLong = L0 + C
        omega = 125.04 - 1934.136 * T

        omega_rad = omega * DEG2RAD
        L0_rad = L0 * DEG2RAD

        lam = trueLong - 0.00569 - 0.00478 * np.sin(omega_rad)

        v = Mr + C * DEG2RAD
        R = (1.000001018 * (1.0 - e * e)) / (1.0 + e * np.cos(v))
        R_km = R * AU

        eps0 = (23.0 +
                (26.0 + (21.448 -
                 (46.8150 * T + 0.00059 * T2 - 0.001813 * T3)) / 60.0) / 60.0)

        sin2L0 = np.sin(2.0 * L0_rad)
        cos2L0 = np.cos(2.0 * L0_rad)
        sin2L0_2M = np.sin(2.0 * L0_rad - 2.0 * Mr)
        cos2L0_2M = np.cos(2.0 * L0_rad - 2.0 * Mr)
        sin2omega = np.sin(2.0 * omega_rad)
        cos2omega = np.cos(2.0 * omega_rad)
        cosomega = np.cos(omega_rad)

        dpsi = (-17.20 * np.sin(omega_rad) -
                1.32 * sin2L0 -
                0.23 * sin2L0_2M +
                0.21 * sin2omega) / 3600.0

        deps = (9.20 * cosomega +
                0.57 * cos2L0 +
                0.10 * cos2L0_2M -
                0.09 * cos2omega) / 3600.0

        eps = eps0 + deps
        eps_rad = eps * DEG2RAD
        lam_rad = lam * DEG2RAD

        sin_lam = np.sin(lam_rad)
        cos_lam = np.cos(lam_rad)
        sin_eps = np.sin(eps_rad)
        cos_eps = np.cos(eps_rad)

        sin_dec = sin_eps * sin_lam
        cos_dec = np.sqrt(np.maximum(0.0, 1.0 - sin_dec * sin_dec))
        dec = np.arctan2(sin_dec, cos_dec)

        ra = np.arctan2(cos_eps * sin_lam, cos_lam)
        if ra < 0.0:
            ra += TWOPI

        cos_dec_val = np.cos(dec)
        sunECI = R_km * np.array([
            cos_dec_val * np.cos(ra),
            cos_dec_val * np.sin(ra),
            np.sin(dec)
        ])

        JD_UT1 = JD + UT1_UTC / 86400.0
        T_ut1 = (JD_UT1 - 2451545.0) / 36525.0
        T_ut1_2 = T_ut1 * T_ut1
        T_ut1_3 = T_ut1_2 * T_ut1

        GMST_sec = (67310.54841 +
                    (876600 * 3600 + 8640184.812866) * T_ut1 +
                    0.093104 * T_ut1_2 -
                    6.2e-6 * T_ut1_3)

        GMST_sec %= 86400.0
        GMST_rad = GMST_sec * (TWOPI / 86400.0)

        c = np.cos(GMST_rad)
        s = np.sin(GMST_rad)

        x = c * sunECI[0] + s * sunECI[1]
        y = -s * sunECI[0] + c * sunECI[1]
        z = sunECI[2]
        sunECEF = np.array([x, y, z])

        if polar is not None:
            xp = polar[0] * ARCSEC2RAD
            yp = polar[1] * ARCSEC2RAD

            cxp = np.cos(xp)
            sxp = np.sin(xp)
            cyp = np.cos(yp)
            syp = np.sin(yp)

            # Rx @ sunECEF
            x1 = sunECEF[0]
            y1 = cxp * sunECEF[1] + sxp * sunECEF[2]
            z1 = -sxp * sunECEF[1] + cxp * sunECEF[2]

            # Ry @ (...)
            sunECEF = np.array([
                cyp * x1 - syp * z1,
                y1,
                syp * x1 + cyp * z1
            ])

        return sunECEF

    # ==========================================================
    #  Ray-sampling shadow test (ellipsoidal Earth, ECEF)
    # ==========================================================
    @staticmethod
    def _normalize_vector(v):
        return v / np.linalg.norm(v)

    @staticmethod
    def ecef_ray_ellipsoid_shadow(rSat, rSun,
                                  a=6378.137,
                                  b=6356.7523,
                                  Rsun=695700.0,
                                  Nsamples=64):
        """
        ecefRayEllipsoidShadow  Ray-sampling shadow test in ECEF (ellipsoidal Earth)
        """

        rSat = np.asarray(rSat, dtype=float).reshape(3)
        rSun = np.asarray(rSun, dtype=float).reshape(3)

        # ==================================================
        # 0) CACHE
        # ==================================================
        if not hasattr(SunEarthGeometry, "_shadow_cache"):
            SunEarthGeometry._shadow_cache = {}

        key = (Nsamples, a, b)
        if key not in SunEarthGeometry._shadow_cache:
            phis = np.linspace(0.0, 2.0 * np.pi, Nsamples, endpoint=False)
            cos_phis = np.cos(phis)
            sin_phis = np.sin(phis)
            inv_a2 = 1.0 / (a * a)
            inv_b2 = 1.0 / (b * b)
            SunEarthGeometry._shadow_cache[key] = (cos_phis, sin_phis, inv_a2, inv_b2)

        cos_phis, sin_phis, inv_a2, inv_b2 = SunEarthGeometry._shadow_cache[key]

        # ==================================================
        # 1) CENTRAL SUN DIRECTION
        # ==================================================
        vSun = rSun - rSat
        Ds = np.linalg.norm(vSun)
        uSun = vSun / Ds

        thetaS = np.arcsin(min(1.0, Rsun / Ds))
        cth = np.cos(thetaS)
        sth = np.sin(thetaS)

        # --------------------------------------------------
        # 2) ORTHONORMAL BASIS
        # --------------------------------------------------
        if abs(uSun[0]) < 0.9:
            tmp = np.array([1.0, 0.0, 0.0])
        else:
            tmp = np.array([0.0, 1.0, 0.0])

        u1 = tmp - np.dot(tmp, uSun) * uSun
        u1 /= np.linalg.norm(u1)
        u2 = np.cross(uSun, u1)
        u2 /= np.linalg.norm(u2)

        # --------------------------------------------------
        # 3) SAMPLE RAYS (VECTORIZE)
        # --------------------------------------------------
        dirs = (
            cth * uSun[:, None] +
            sth * (u1[:, None] * cos_phis[None, :] + u2[:, None] * sin_phis[None, :])
        )

        # --------------------------------------------------
        # 4) QUADRATIC INTERSECTION TEST (VECTORIZE)
        # --------------------------------------------------
        maxRayDist = Ds + Rsun * 1.1

        dx = dirs[0]
        dy = dirs[1]
        dz = dirs[2]

        r0x, r0y, r0z = rSat

        A = inv_a2 * (dx * dx + dy * dy) + inv_b2 * (dz * dz)
        B = 2.0 * (inv_a2 * (r0x * dx + r0y * dy) + inv_b2 * (r0z * dz))
        C = inv_a2 * (r0x * r0x + r0y * r0y) + inv_b2 * (r0z * r0z) - 1.0

        disc = B * B - 4.0 * A * C
        blocked = np.zeros(Nsamples, dtype=bool)

        valid_disc = disc >= 0.0
        if np.any(valid_disc):
            eps = np.finfo(float).eps
            linear_mask = valid_disc & (np.abs(A) < eps)
            quad_mask = valid_disc & ~linear_mask

            if np.any(linear_mask):
                B_lin = B[linear_mask]
                C_lin = C
                t_lin = -C_lin / B_lin
                blocked[linear_mask] = (t_lin > 1e-8) & (t_lin < maxRayDist)

            if np.any(quad_mask):
                A_q = A[quad_mask]
                B_q = B[quad_mask]
                sqrtD = np.sqrt(disc[quad_mask])

                denom = 2.0 * A_q
                t1 = (-B_q - sqrtD) / denom
                t2 = (-B_q + sqrtD) / denom

                ok1 = (t1 > 1e-8) & (t1 < maxRayDist)
                ok2 = (t2 > 1e-8) & (t2 < maxRayDist)
                blocked[quad_mask] = ok1 | ok2

        blockedFraction = blocked.mean()
        shadowFactor = 1.0 - blockedFraction

        if blockedFraction == 0.0:
            status = 0
        elif blockedFraction == 1.0:
            status = 2
        else:
            status = 1

        return status, shadowFactor

    # ==========================================================
    #  Eclipse column computation for DataFrame
    # ==========================================================
    @staticmethod
    def compute_eclipse(df):
        """
        df: pandas DataFrame
            Required columns: epoch, X_ref, Y_ref, Z_ref (meters)

        Returns
        -------
        df_out : DataFrame
            New column 'eclipse' is added:
               0 = illuminated
               1 = penumbra
               2 = umbra
        """

        import pandas as pd
        from datetime import datetime

        df = df.copy()

        # --------------------------------------------------
        # 1) normalize epochs
        # --------------------------------------------------
        epochs = pd.to_datetime(df["epoch"])
        df["epoch"] = epochs

        # --------------------------------------------------
        # 2) UNIQUE epoch -> Sun position cache
        # --------------------------------------------------
        epoch_codes, unique_epochs = pd.factorize(epochs, sort=False)
        sun_positions = np.empty((len(unique_epochs), 3), dtype=float)

        for i, t in enumerate(unique_epochs):
            sun_positions[i] = SunEarthGeometry.sun_position_ecef_highprec(t)

        # --------------------------------------------------
        rSat_all = df[["X_ref", "Y_ref", "Z_ref"]].to_numpy(dtype=float) / 1000.0
        sun_all = sun_positions[epoch_codes]

        eclipse = np.empty(len(df), dtype=np.int8)

        # --------------------------------------------------
        # 4) Fast loop
        # --------------------------------------------------
        for i in range(len(df)):
            status, _ = SunEarthGeometry.ecef_ray_ellipsoid_shadow(
                rSat_all[i], sun_all[i]
            )
            eclipse[i] = status

        df["eclipse"] = eclipse
        return df
