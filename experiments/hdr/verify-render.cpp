// Exercise the patched compositor's luminance transform and actual GLSL on an
// offscreen Mesa context. This measures code values, not physical panel nits.
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl3.h>
#include <algorithm>
#include <array>
#include <cmath>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>
#include <string>
#include "src/helpers/cm/Edr.hpp"

namespace fs = std::filesystem;
using NColorManagement::EDR::luminanceTransform;

static std::string readShader(const fs::path& path) {
    // ShaderLoader replaces this editor-only file with variant feature flags.
    if (path.filename() == "defines.h")
        return {};
    std::ifstream file(path);
    if (!file)
        throw std::runtime_error("Cannot read " + path.string());
    std::string result, line;
    while (std::getline(file, line)) {
        if (line.starts_with("#include \"")) {
            const auto end = line.find('"', 10);
            result += readShader(path.parent_path() / line.substr(10, end - 10));
        } else
            result += line + '\n';
    }
    return result;
}

static GLuint compile(GLenum type, const std::string& text) {
    GLuint shader = glCreateShader(type);
    const char* data = text.c_str();
    glShaderSource(shader, 1, &data, nullptr);
    glCompileShader(shader);
    GLint ok = 0;
    glGetShaderiv(shader, GL_COMPILE_STATUS, &ok);
    if (!ok) {
        char log[8192]{};
        glGetShaderInfoLog(shader, sizeof(log), nullptr, log);
        throw std::runtime_error(log);
    }
    return shader;
}

static double pq(double nits) {
    const double p = std::pow(nits / 10000., 2610. / 16384.);
    return std::pow((3424. / 4096. + (2413. / 128.) * p) / (1. + (2392. / 128.) * p), 2523. / 32.);
}

static void expect(const std::string& name, double actual, double expected, double tolerance = 0.002) {
    if (!std::isfinite(actual) || std::abs(actual - expected) > tolerance)
        throw std::runtime_error(name + ": got " + std::to_string(actual) + ", expected " + std::to_string(expected));
    std::cout << "PASS " << name << ": " << actual << '\n';
}

int main(int argc, char** argv) {
    try {
        if (argc != 2)
            throw std::runtime_error("Usage: verify-render PATCHED_HYPRLAND_SOURCE");
        const auto display = eglGetPlatformDisplay(EGL_PLATFORM_SURFACELESS_MESA, EGL_DEFAULT_DISPLAY, nullptr);
        if (display == EGL_NO_DISPLAY || !eglInitialize(display, nullptr, nullptr))
            throw std::runtime_error("Cannot initialize surfaceless EGL");
        eglBindAPI(EGL_OPENGL_ES_API);
        const EGLint attrs[] = {EGL_SURFACE_TYPE, EGL_PBUFFER_BIT, EGL_RENDERABLE_TYPE, EGL_OPENGL_ES3_BIT, EGL_NONE};
        EGLConfig config;
        EGLint count;
        if (!eglChooseConfig(display, attrs, &config, 1, &count) || !count)
            throw std::runtime_error("No GLES3 EGL configuration");
        const EGLint contextAttrs[] = {EGL_CONTEXT_CLIENT_VERSION, 3, EGL_NONE};
        const auto context = eglCreateContext(display, config, EGL_NO_CONTEXT, contextAttrs);
        const EGLint surfaceAttrs[] = {EGL_WIDTH, 1, EGL_HEIGHT, 1, EGL_NONE};
        const auto surface = eglCreatePbufferSurface(display, config, surfaceAttrs);
        if (!eglMakeCurrent(display, surface, surface, context))
            throw std::runtime_error("Cannot make EGL context current");
        std::cout << "Renderer: " << glGetString(GL_RENDERER) << '\n';

        const std::string vertex = R"(#version 300 es
        void main() {
            vec2 p = vec2(float((gl_VertexID << 1) & 2), float(gl_VertexID & 2));
            gl_Position = vec4(p * 2.0 - 1.0, 0.0, 1.0);
        })";
        const std::string fragment = std::string(R"(#version 300 es
        precision highp float;
        precision highp int;
        #define ALLOW_INCLUDES
        #define USE_TONEMAP 1
        #define USE_ALT_TONEMAP 1
        #define USE_SDR_MOD 0
        #define USE_MIRROR 0
        #define USE_ICC 0
        )") + readShader(fs::path(argv[1]) / "src/render/shaders/glsl/cm_helpers.glsl") + R"(
        uniform vec4 sampleColor;
        uniform int sourceTF, targetTF;
        uniform float sourcePeak, targetPeak, contentPeak, panelPeak, referenceWhite;
        out vec4 result;
        void main() {
            mat3 p3xyz = mat3(0.486571,0.228975,0.0, 0.265668,0.691739,0.045113,
                             0.198217,0.079287,1.043944);
            result = doColorManagement(sampleColor, 1.0, sourceTF, targetTF,
                     mat3(1.0), vec2(0.0,sourcePeak), vec2(0.0,targetPeak),
                     p3xyz, contentPeak, panelPeak, referenceWhite, referenceWhite, 3);
        })";
        const auto program = glCreateProgram();
        glAttachShader(program, compile(GL_VERTEX_SHADER, vertex));
        glAttachShader(program, compile(GL_FRAGMENT_SHADER, fragment));
        glLinkProgram(program);
        GLint linked;
        glGetProgramiv(program, GL_LINK_STATUS, &linked);
        if (!linked) {
            char log[8192]{};
            glGetProgramInfoLog(program, sizeof(log), nullptr, log);
            throw std::runtime_error(log);
        }
        glUseProgram(program);
        GLuint texture, framebuffer;
        glGenTextures(1, &texture);
        glBindTexture(GL_TEXTURE_2D, texture);
        glTexStorage2D(GL_TEXTURE_2D, 1, GL_RGBA32F, 1, 1);
        glGenFramebuffers(1, &framebuffer);
        glBindFramebuffer(GL_FRAMEBUFFER, framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, texture, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE)
            throw std::runtime_error("No floating-point framebuffer support");
        glViewport(0, 0, 1, 1);

        auto render = [&](double code, int srcTF, int dstTF, float srcPeak, float srcRef, float contentPeak,
                          float dstPeak = 500, float dstRef = 200, float panelPeak = 500) {
            const auto t = luminanceTransform(srcPeak, srcRef, contentPeak, dstPeak, dstRef);
            auto f = [&](const char* name, float value) { glUniform1f(glGetUniformLocation(program, name), value); };
            glUniform4f(glGetUniformLocation(program, "sampleColor"), code, code, code, 1);
            glUniform1i(glGetUniformLocation(program, "sourceTF"), srcTF);
            glUniform1i(glGetUniformLocation(program, "targetTF"), dstTF);
            f("sourcePeak", t.sourceEncodingPeak);
            f("targetPeak", t.targetEncodingPeak);
            f("contentPeak", t.sourceContentPeak);
            f("panelPeak", panelPeak);
            f("referenceWhite", dstRef);
            glDrawArrays(GL_TRIANGLES, 0, 3);
            std::array<float, 4> pixel;
            glReadPixels(0, 0, 1, 1, GL_RGBA, GL_FLOAT, pixel.data());
            if (glGetError() != GL_NO_ERROR)
                throw std::runtime_error("OpenGL rendering/readback error");
            for (auto c : pixel)
                if (!std::isfinite(c))
                    throw std::runtime_error("Non-finite rendered channel");
            if (std::abs(pixel[0] - pixel[1]) > 0.002 || std::abs(pixel[0] - pixel[2]) > 0.002)
                throw std::runtime_error("Neutral input acquired a color cast");
            return pixel[0];
        };
        // Transfer-function numbers are defined by color-management-v1 and Hyprland.
        constexpr int GAMMA22 = 2, SCRGB = 5, SRGB = 9, PQ = 11;
        const double whiteCode = std::pow(200. / 500., 1. / 2.2);
        expect("SDR white uses 200/500 of panel light", render(1, SRGB, GAMMA22, 80, 80, 80), whiteCode);
        expect("tagged SDR white agrees", render(1, GAMMA22, GAMMA22, 100, 100, 100), whiteCode);
        expect("PQ reference white agrees", render(pq(203), PQ, GAMMA22, 10000, 203, 507.5), whiteCode);
        expect("scRGB reference white agrees", render(203. / 80., SCRGB, GAMMA22, 80, 203, 507.5), whiteCode);
        expect("HDR reaches panel peak", render(pq(507.5), PQ, GAMMA22, 10000, 203, 507.5), 1);
        expect("black remains black", render(0, SRGB, GAMMA22, 80, 80, 80), 0);
        expect("preferred gamma client keeps its values", render(whiteCode, GAMMA22, GAMMA22, 500, 200, 500), whiteCode);
        const auto workingWhite = render(1, SRGB, SCRGB, 80, 80, 80, 80);
        expect("working buffer preserves values above one", workingWhite, 2.5);
        expect("two-pass white scales only once", render(workingWhite, SCRGB, GAMMA22, 80, 200, 500), whiteCode);
        const auto workingHighlight = render(pq(507.5), PQ, SCRGB, 10000, 203, 507.5, 80);
        expect("working buffer preserves highlight", workingHighlight, 6.25);
        expect("two-pass highlight reaches peak", render(workingHighlight, SCRGB, GAMMA22, 80, 200, 500), 1);
        // Blur temporarily gamma-encodes the scene, keeping its peak/reference.
        const auto blurWhite = render(workingWhite, SCRGB, GAMMA22, 80, 200, 500);
        expect("blur white round trip", render(blurWhite, GAMMA22, SCRGB, 500, 200, 500, 80), workingWhite);
        const auto blurHighlight = render(workingHighlight, SCRGB, GAMMA22, 80, 200, 500);
        expect("blur highlight round trip", render(blurHighlight, GAMMA22, SCRGB, 500, 200, 500, 80), workingHighlight);
        expect("1000-nit content preserves reference white", render(pq(203), PQ, GAMMA22, 10000, 203, 1000), whiteCode);
        float previous = -1;
        for (int nits = 0; nits <= 1000; nits += 10) {
            const float value = render(pq(nits), PQ, GAMMA22, 10000, 203, 1000);
            if (value + 0.0002 < previous || value > 1.002 || value < -0.002)
                throw std::runtime_error("Tone mapping is not monotonic and bounded");
            previous = value;
        }
        expect("1000-nit content rolls off to peak", previous, 1, 0.004);
        eglMakeCurrent(display, EGL_NO_SURFACE, EGL_NO_SURFACE, EGL_NO_CONTEXT);
        eglDestroyContext(display, context);
        eglDestroySurface(display, surface);
        eglTerminate(display);
    } catch (const std::exception& error) {
        std::cerr << error.what() << '\n';
        return 1;
    }
}
