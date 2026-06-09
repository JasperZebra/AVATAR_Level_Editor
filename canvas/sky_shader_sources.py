"""
Embedded GLSL sources for the daytime atmosphere sky (sky_atmosphere.py).

These are fgarlin's spectral-sky ShaderToy sources (Common + Buffer A
transmittance LUT [Bruneton & Neyret 2008] + Buffer B sky-view LUT
[Hillaire 2020]), embedded VERBATIM as Python strings so the editor has no
runtime file dependency (the old canvas/Night Sky/Shader toy/*.txt files
were loose on disk, never in git, and got lost once - and loose files also
had to be bundled separately for frozen builds).

Do NOT hand-edit the GLSL here: sky_atmosphere._adapt_common() still patches
get_sun_direction() into a uniform at runtime, exactly as it did with the
files. The wrapping/adaptation all lives in sky_atmosphere.py; this module
is data only.
"""

COMMON = """\
// Configurable parameters

#define ANIMATE_SUN 1
// 0=equirectangular, 1=fisheye, 2=projection
#define CAMERA_TYPE 2
// 0=Background, 1=Desert Dust, 2=Maritime Clean, 3=Maritime Mineral,
// 4=Polar Antarctic, 5=Polar Artic, 6=Remote Continental, 7=Rural, 8=Urban
#define AEROSOL_TYPE 8

const float SUN_ELEVATION_DEGREES = 0.0;    // 0=horizon, 90=zenith
const float EYE_ALTITUDE          = 0.5;    // km
const int   MONTH                 = 0;      // 0-11, January to December
const float AEROSOL_TURBIDITY     = 1.0;
const vec4  GROUND_ALBEDO         = vec4(0.3);
// Ray marching steps. More steps mean better accuracy but worse performance
const int TRANSMITTANCE_STEPS     = 32;
const int IN_SCATTERING_STEPS     = 32;
// Camera settings
const float EXPOSURE              = -4.0;
// For the "projection" type camera
const float CAMERA_FOV   =  90.0;
const float CAMERA_YAW   =  15.0;
const float CAMERA_PITCH = -12.0;
const float CAMERA_ROLL  =   0.0;

// Debug
#define ENABLE_SPECTRAL 1
#define ENABLE_MULTIPLE_SCATTERING 1
#define ENABLE_AEROSOLS 1
#define SHOW_RELATIVE_LUMINANCE 0
#define TONEMAPPING_TECHNIQUE 0 // 0=ACES, 1=simple

//-----------------------------------------------------------------------------
// Constants

// All parameters that depend on wavelength (vec4) are sampled at
// 630, 560, 490, 430 nanometers

const float PI = 3.14159265358979323846;
const float INV_PI = 0.31830988618379067154;
const float INV_4PI = 0.25 * INV_PI;
const float PHASE_ISOTROPIC = INV_4PI;
const float RAYLEIGH_PHASE_SCALE = (3.0 / 16.0) * INV_PI;
const float g = 0.8;
const float gg = g*g;

const float EARTH_RADIUS = 6371.0; // km
const float ATMOSPHERE_THICKNESS = 100.0; // km
const float ATMOSPHERE_RADIUS = EARTH_RADIUS + ATMOSPHERE_THICKNESS;
const float EYE_DISTANCE_TO_EARTH_CENTER = EARTH_RADIUS + EYE_ALTITUDE;
const float SUN_ZENITH_COS_ANGLE = cos(radians(90.0 - SUN_ELEVATION_DEGREES));
const vec3 SUN_DIR = vec3(-sqrt(1.0 - SUN_ZENITH_COS_ANGLE*SUN_ZENITH_COS_ANGLE), 0.0, SUN_ZENITH_COS_ANGLE);

#if ENABLE_SPECTRAL == 1
// Extraterrestial Solar Irradiance Spectra, units W * m^-2 * nm^-1
// https://www.nrel.gov/grid/solar-resource/spectra.html
const vec4 sun_spectral_irradiance = vec4(1.679, 1.828, 1.986, 1.307);
// Rayleigh scattering coefficient at sea level, units km^-1
// "Rayleigh-scattering calculations for the terrestrial atmosphere"
// by Anthony Bucholtz (1995).
const vec4 molecular_scattering_coefficient_base = vec4(6.605e-3, 1.067e-2, 1.842e-2, 3.156e-2);
// Ozone absorption cross section, units m^2 / molecules
// "High spectral resolution ozone absorption cross-sections"
// by V. Gorshelev et al. (2014).
const vec4 ozone_absorption_cross_section = vec4(3.472e-21, 3.914e-21, 1.349e-21, 11.03e-23) * 1e-4f;
#else
// Same as above but for the following "RGB" wavelengths: 680, 550, 440 nm
// The Sun spectral irradiance is also multiplied by a constant factor to
// compensate for the fact that we use the spectral samples directly as RGB,
// which is incorrect.
const vec4 sun_spectral_irradiance = vec4(1.500, 1.864, 1.715, 0.0) * 150.0;
const vec4 molecular_scattering_coefficient_base = vec4(4.847e-3, 1.149e-2, 2.870e-2, 0.0);
const vec4 ozone_absorption_cross_section = vec4(3.36e-21f, 3.08e-21f, 20.6e-23f, 0.0) * 1e-4f;
#endif

// Mean ozone concentration in Dobson for each month of the year.
const float ozone_mean_monthly_dobson[] = float[](
    347.0, // January
    370.0, // February
    381.0, // March
    384.0, // April
    372.0, // May
    352.0, // June
    333.0, // July
    317.0, // August
    298.0, // September
    285.0, // October
    290.0, // November
    315.0  // December
);

/*
 * Every aerosol type expects 5 parameters:
 * - Scattering cross section
 * - Absorption cross section
 * - Base density (km^-3)
 * - Background density (km^-3)
 * - Height scaling parameter
 * These parameters can be sent as uniforms.
 *
 * This model for aerosols and their corresponding parameters come from
 * "A Physically-Based Spatio-Temporal Sky Model"
 * by Guimera et al. (2018).
 */
#if   AEROSOL_TYPE == 0 // Background
const vec4 aerosol_absorption_cross_section = vec4(4.5517e-19, 5.9269e-19, 6.9143e-19, 8.5228e-19);
const vec4 aerosol_scattering_cross_section = vec4(1.8921e-26, 1.6951e-26, 1.7436e-26, 2.1158e-26);
const float aerosol_base_density = 2.584e17;
const float aerosol_background_density = 2e6;
#elif AEROSOL_TYPE == 1 // Desert Dust
const vec4 aerosol_absorption_cross_section = vec4(4.6758e-16, 4.4654e-16, 4.1989e-16, 4.1493e-16);
const vec4 aerosol_scattering_cross_section = vec4(2.9144e-16, 3.1463e-16, 3.3902e-16, 3.4298e-16);
const float aerosol_base_density = 1.8662e18;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 2.0;
#elif AEROSOL_TYPE == 2 // Maritime Clean
const vec4 aerosol_absorption_cross_section = vec4(6.3312e-19, 7.5567e-19, 9.2627e-19, 1.0391e-18);
const vec4 aerosol_scattering_cross_section = vec4(4.6539e-26, 2.721e-26, 4.1104e-26, 5.6249e-26);
const float aerosol_base_density = 2.0266e17;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 0.9;
#elif AEROSOL_TYPE == 3 // Maritime Mineral
const vec4 aerosol_absorption_cross_section = vec4(6.9365e-19, 7.5951e-19, 8.2423e-19, 8.9101e-19);
const vec4 aerosol_scattering_cross_section = vec4(2.3699e-19, 2.2439e-19, 2.2126e-19, 2.021e-19);
const float aerosol_base_density = 2.0266e17;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 2.0;
#elif AEROSOL_TYPE == 4 // Polar Antarctic
const vec4 aerosol_absorption_cross_section = vec4(1.3399e-16, 1.3178e-16, 1.2909e-16, 1.3006e-16);
const vec4 aerosol_scattering_cross_section = vec4(1.5506e-19, 1.809e-19, 2.3069e-19, 2.5804e-19);
const float aerosol_base_density = 2.3864e16;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 30.0;
#elif AEROSOL_TYPE == 5 // Polar Arctic
const vec4 aerosol_absorption_cross_section = vec4(1.0364e-16, 1.0609e-16, 1.0193e-16, 1.0092e-16);
const vec4 aerosol_scattering_cross_section = vec4(2.1609e-17, 2.2759e-17, 2.5089e-17, 2.6323e-17);
const float aerosol_base_density = 2.3864e16;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 30.0;
#elif AEROSOL_TYPE == 6 // Remote Continental
const vec4 aerosol_absorption_cross_section = vec4(4.5307e-18, 5.0662e-18, 4.4877e-18, 3.7917e-18);
const vec4 aerosol_scattering_cross_section = vec4(1.8764e-18, 1.746e-18, 1.6902e-18, 1.479e-18);
const float aerosol_base_density = 6.103e18;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 0.73;
#elif AEROSOL_TYPE == 7 // Rural
const vec4 aerosol_absorption_cross_section = vec4(5.0393e-23, 8.0765e-23, 1.3823e-22, 2.3383e-22);
const vec4 aerosol_scattering_cross_section = vec4(2.6004e-22, 2.4844e-22, 2.8362e-22, 2.7494e-22);
const float aerosol_base_density = 8.544e18;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 0.73;
#elif AEROSOL_TYPE == 8 // Urban
const vec4 aerosol_absorption_cross_section = vec4(2.8722e-24, 4.6168e-24, 7.9706e-24, 1.3578e-23);
const vec4 aerosol_scattering_cross_section = vec4(1.5908e-22, 1.7711e-22, 2.0942e-22, 2.4033e-22);
const float aerosol_base_density = 1.3681e20;
const float aerosol_background_density = 2e6;
const float aerosol_height_scale = 0.73;
#endif
const float aerosol_background_divided_by_base_density = aerosol_background_density / aerosol_base_density;

//-----------------------------------------------------------------------------

vec3 get_sun_direction(float time)
{
#if ANIMATE_SUN == 0
    return SUN_DIR;
#else
    float a = sin(time*0.5 - 1.5) * 0.55 + 0.45;
    return vec3(-sqrt(1.0 - a*a), 0.0, a);
#endif
}

/*
 * Helper function to obtain the transmittance to the top of the atmosphere
 * from Buffer A.
 */
vec4 transmittance_from_lut(sampler2D lut, float cos_theta, float normalized_altitude)
{
    float u = clamp(cos_theta * 0.5 + 0.5, 0.0, 1.0);
    float v = clamp(normalized_altitude, 0.0, 1.0);
    return texture(lut, vec2(u, v));
}

/*
 * Returns the distance between ro and the first intersection with the sphere
 * or -1.0 if there is no intersection. The sphere's origin is (0,0,0).
 * -1.0 is also returned if the ray is pointing away from the sphere.
 */
float ray_sphere_intersection(vec3 ro, vec3 rd, float radius)
{
    float b = dot(ro, rd);
    float c = dot(ro, ro) - radius*radius;
    if (c > 0.0 && b > 0.0) return -1.0;
    float d = b*b - c;
    if (d < 0.0) return -1.0;
    if (d > b*b) return (-b+sqrt(d));
    return (-b-sqrt(d));
}

/*
 * Rayleigh phase function.
 */
float molecular_phase_function(float cos_theta)
{
    return RAYLEIGH_PHASE_SCALE * (1.0 + cos_theta*cos_theta);
}

/*
 * Henyey-Greenstrein phase function.
 */
float aerosol_phase_function(float cos_theta)
{
    float den = 1.0 + gg + 2.0 * g * cos_theta;
    return INV_4PI * (1.0 - gg) / (den * sqrt(den));
}

vec4 get_multiple_scattering(sampler2D transmittance_lut, float cos_theta, float normalized_height, float d)
{
#if ENABLE_MULTIPLE_SCATTERING == 1
    // Solid angle subtended by the planet from a point at d distance
    // from the planet center.
    float omega = 2.0 * PI * (1.0 - sqrt(d*d - EARTH_RADIUS*EARTH_RADIUS) / d);

    vec4 T_to_ground = transmittance_from_lut(transmittance_lut, cos_theta, 0.0);

    vec4 T_ground_to_sample =
        transmittance_from_lut(transmittance_lut, 1.0, 0.0) /
        transmittance_from_lut(transmittance_lut, 1.0, normalized_height);

    // 2nd order scattering from the ground
    vec4 L_ground = PHASE_ISOTROPIC * omega * (GROUND_ALBEDO / PI) * T_to_ground * T_ground_to_sample * cos_theta;

    // Fit of Earth's multiple scattering coming from other points in the atmosphere
    vec4 L_ms = 0.02 * vec4(0.217, 0.347, 0.594, 1.0) * (1.0 / (1.0 + 5.0 * exp(-17.92 * cos_theta)));

    return L_ms + L_ground;
#else
    return vec4(0.0);
#endif
}

/*
 * Return the molecular volume scattering coefficient (km^-1) for a given altitude
 * in kilometers.
 */
vec4 get_molecular_scattering_coefficient(float h)
{
    return molecular_scattering_coefficient_base * exp(-0.07771971 * pow(h, 1.16364243));
}

/*
 * Return the molecular volume absorption coefficient (km^-1) for a given altitude
 * in kilometers.
 */
vec4 get_molecular_absorption_coefficient(float h)
{
    h += 1e-4; // Avoid division by 0
    float t = log(h) - 3.22261;
    float density = 3.78547397e20 * (1.0 / h) * exp(-t * t * 5.55555555);
    return ozone_absorption_cross_section * ozone_mean_monthly_dobson[MONTH] * density;
}

float get_aerosol_density(float h)
{
#if AEROSOL_TYPE == 0 // Only for the Background aerosol type, no dependency on height
    return aerosol_base_density * (1.0 + aerosol_background_divided_by_base_density);
#else
    return aerosol_base_density * (exp(-h / aerosol_height_scale)
        + aerosol_background_divided_by_base_density);
#endif
}

/*
 * Get the collision coefficients (scattering and absorption) of the
 * atmospheric medium for a given point at an altitude h.
 */
void get_atmosphere_collision_coefficients(in float h,
                                           out vec4 aerosol_absorption,
                                           out vec4 aerosol_scattering,
                                           out vec4 molecular_absorption,
                                           out vec4 molecular_scattering,
                                           out vec4 extinction)
{
    h = max(h, 0.0); // In case height is negative
#if ENABLE_AEROSOLS == 0
    aerosol_absorption = vec4(0.0);
    aerosol_scattering = vec4(0.0);
#else
    float aerosol_density = get_aerosol_density(h);
    aerosol_absorption = aerosol_absorption_cross_section * aerosol_density * AEROSOL_TURBIDITY;
    aerosol_scattering = aerosol_scattering_cross_section * aerosol_density * AEROSOL_TURBIDITY;
#endif
    molecular_absorption = get_molecular_absorption_coefficient(h);
    molecular_scattering = get_molecular_scattering_coefficient(h);
    extinction = aerosol_absorption + aerosol_scattering + molecular_absorption + molecular_scattering;
}

//-----------------------------------------------------------------------------
// Spectral rendering stuff

const mat4x3 M = mat4x3(
    137.672389239975, -8.632904716299537, -1.7181567391931372,
    32.549094028629234, 91.29801417199785, -12.005406444382531,
    -38.91428392614275, 34.31665471469816, 29.89044807197628,
    8.572844237945445, -11.103384660054624, 117.47585277566478
);

vec3 linear_srgb_from_spectral_samples(vec4 L)
{
    return M * L;
}"""

BUFFER_A = """\
/*
 * Buffer A: Transmittance LUT
 *
 * In this buffer we precompute the transmittance to the top of the atmosphere.
 * We use the same technique as in "Precomputed Atmospheric Scattering"
 * by Eric Bruneton and Fabrice Neyret (2008).
 */

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;

    float sun_cos_theta = uv.x * 2.0 - 1.0;
    vec3 sun_dir = vec3(-sqrt(1.0 - sun_cos_theta*sun_cos_theta), 0.0, sun_cos_theta);

    float distance_to_earth_center = mix(EARTH_RADIUS, ATMOSPHERE_RADIUS, uv.y);
    vec3 ray_origin = vec3(0.0, 0.0, distance_to_earth_center);

    float t_d = ray_sphere_intersection(ray_origin, sun_dir, ATMOSPHERE_RADIUS);
    float dt = t_d / float(TRANSMITTANCE_STEPS);

    vec4 result = vec4(0.0);

    for (int i = 0; i < TRANSMITTANCE_STEPS; ++i) {
        float t = (float(i) + 0.5) * dt;
        vec3 x_t = ray_origin + sun_dir * t;

        float altitude = length(x_t) - EARTH_RADIUS;

        vec4 aerosol_absorption, aerosol_scattering;
        vec4 molecular_absorption, molecular_scattering;
        vec4 extinction;
        get_atmosphere_collision_coefficients(
            altitude,
            aerosol_absorption, aerosol_scattering,
            molecular_absorption, molecular_scattering,
            extinction);

        result += extinction * dt;
    }

    vec4 transmittance = exp(-result);
    fragColor = transmittance;
}
"""

BUFFER_B = """\
/*
 * Buffer B: Sky texture
 *
 * "A Scalable and Production Ready Sky and Atmosphere Rendering Technique"
 * by Sébastien Hillaire (2020).
 *
 * We render the sky to a texture instead of raymarching on the entire screen.
 * This is not very useful in Shadertoy, but very useful for someone looking
 * to implement this on a real application.
 *
 * It is important to note that quality decreases significantly when rendering
 * space views. To avoid this, the compute_inscattering() function can be used
 * directly when rendering to a fullscreen quad.
 */
 
vec4 compute_inscattering(vec3 ray_origin, vec3 ray_dir, float t_d, out vec4 transmittance)
{
    vec3 sun_dir = get_sun_direction(iTime);
    float cos_theta = dot(-ray_dir, sun_dir);

    float molecular_phase = molecular_phase_function(cos_theta);
    float aerosol_phase = aerosol_phase_function(cos_theta);

    float dt = t_d / float(IN_SCATTERING_STEPS);

    vec4 L_inscattering = vec4(0.0);
    transmittance = vec4(1.0);

    for (int i = 0; i < IN_SCATTERING_STEPS; ++i) {
        float t = (float(i) + 0.5) * dt;
        vec3 x_t = ray_origin + ray_dir * t;

        float distance_to_earth_center = length(x_t);
        vec3 zenith_dir = x_t / distance_to_earth_center;
        float altitude = distance_to_earth_center - EARTH_RADIUS;
        float normalized_altitude = altitude / ATMOSPHERE_THICKNESS;

        float sample_cos_theta = dot(zenith_dir, sun_dir);

        vec4 aerosol_absorption, aerosol_scattering;
        vec4 molecular_absorption, molecular_scattering;
        vec4 extinction;
        get_atmosphere_collision_coefficients(
            altitude,
            aerosol_absorption, aerosol_scattering,
            molecular_absorption, molecular_scattering,
            extinction);

        vec4 transmittance_to_sun = transmittance_from_lut(
            iChannel0, sample_cos_theta, normalized_altitude);

        vec4 ms = get_multiple_scattering(
            iChannel0, sample_cos_theta, normalized_altitude,
            distance_to_earth_center);

        vec4 S = sun_spectral_irradiance *
            (molecular_scattering * (molecular_phase * transmittance_to_sun + ms) +
             aerosol_scattering   * (aerosol_phase   * transmittance_to_sun + ms));

        vec4 step_transmittance = exp(-dt * extinction);

        // Energy-conserving analytical integration
        // "Physically Based Sky, Atmosphere and Cloud Rendering in Frostbite"
        // by Sébastien Hillaire
        vec4 S_int = (S - S * step_transmittance) / max(extinction, 1e-7);
        L_inscattering += transmittance * S_int;
        transmittance *= step_transmittance;
    }

    return L_inscattering;
}

void mainImage(out vec4 fragColor, in vec2 fragCoord)
{
    vec2 uv = fragCoord / iResolution.xy;

    float azimuth = 2.0 * PI * uv.x;

    // Apply a non-linear transformation to the elevation to dedicate more
    // texels to the horizon, where having more detail matters.
    float l = uv.y * 2.0 - 1.0;
    float elev = l*l * sign(l) * PI * 0.5; // [-pi/2, pi/2]

    vec3 ray_dir = vec3(cos(elev) * cos(azimuth),
                        cos(elev) * sin(azimuth),
                        sin(elev));

    vec3 ray_origin = vec3(0.0, 0.0, EYE_DISTANCE_TO_EARTH_CENTER);

    float atmos_dist  = ray_sphere_intersection(ray_origin, ray_dir, ATMOSPHERE_RADIUS);
    float ground_dist = ray_sphere_intersection(ray_origin, ray_dir, EARTH_RADIUS);
    float t_d;
    if (EYE_ALTITUDE < ATMOSPHERE_THICKNESS) {
        // We are inside the atmosphere
        if (ground_dist < 0.0) {
            // No ground collision, use the distance to the outer atmosphere
            t_d = atmos_dist;
        } else {
            // We have a collision with the ground, use the distance to it
            t_d = ground_dist;
        }
    } else {
        // We are in outer space
        if (atmos_dist < 0.0) {
            // No collision with the atmosphere, just return black
            fragColor = vec4(0.0, 0.0, 0.0, 1.0);
            return;
        } else {
            // Move the ray origin to the atmosphere intersection
            ray_origin = ray_origin + ray_dir * (atmos_dist + 1e-3);
            if (ground_dist < 0.0) {
                // No collision with the ground, so the ray is exiting through
                // the atmosphere.
                float second_atmos_dist = ray_sphere_intersection(
                    ray_origin, ray_dir, ATMOSPHERE_RADIUS);
                t_d = second_atmos_dist;
            } else {
                t_d = ground_dist - atmos_dist;
            }
        }
    }

    vec4 transmittance;
    vec4 L = compute_inscattering(ray_origin, ray_dir, t_d, transmittance);

#if ENABLE_SPECTRAL == 1
    fragColor = vec4(linear_srgb_from_spectral_samples(L), 1.0);
#else
    fragColor = vec4(L.rgb, 1.0);
#endif
}"""

SOURCES = {
    'Common.txt': COMMON,
    'Buffer A.txt': BUFFER_A,
    'Buffer B.txt': BUFFER_B,
}
