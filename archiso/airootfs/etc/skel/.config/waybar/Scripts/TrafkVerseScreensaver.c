/*
Copyright © 2026 TrafkHop Entertainment™
All rights reserved.

This code was written by an AI coding assistant, directed by a human author
who specified the exact requirements and reviewed the result.
*/
// TrafkVerseScreensaver.c — procedurally generates random animated patterns
// on screen, each paired with a generative musical note driven by a
// SoundFont synth (TinySoundFont).
#define SDL_MAIN_HANDLED
#include <SDL2/SDL.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <strings.h>
#include <math.h>
#include <time.h>
#include <dirent.h>
#include <stdint.h>
#include <unistd.h>

#define TSF_IMPLEMENTATION
#include "tsf.h"

#define STBI_ONLY_PNG
#define STBI_NO_LINEAR
#define STB_IMAGE_IMPLEMENTATION
#include "stb_image.h"

int BufW = 640;
int BufH = 360;
#define MaxColors 256
#define MaxEnt    32
#define MaxBody   40

static uint32_t *Pixbuf;
static uint8_t  *Bg;
static uint8_t  *BgTint;
static uint8_t  *FgInt;
static uint16_t *FgCol;

static uint8_t Colors[MaxColors][3];
static int     ColorPreset[MaxColors];
static int     NColors = 0;
static tsf    *Synth = NULL;

static int GScale[7];
static int GScaleSize = 7;
static int GRoot = 48;

static float    GPresence   = 1.0f;
static uint32_t GSeed       = 0;
static float    GBlend      = 0.0f;
static uint32_t GBlendSeed = 0;

static float GPt  = 0.0f;
static float GWf1 = 0.5f, GWf2 = 0.5f;
static float GWa1 = 2.0f, GWa2 = 2.0f;

// menu options (per-run, not persisted)
static int   GOptColors = 0;      // 0 = random
static int   GOptSilent = 1;
static float GOptWobble = 1.0f;
static float GOptWander = 1.0f;
static float GOptBlend  = 1.65f;
static int   GOptPixelsize = 0;   // 0 = auto (resolution-adaptive), 1..6 = forced logical-pixel size
static float GOptAudioreact = 1.0f; // 0..2, strength of motion->sound coupling (pitch/volume)
static float GOptZoom = 1.0f;       // 1.0 = no zoom, >1 crops+magnifies the buffer at blit time
static float GOptFadeMul = 1.0f;    // scales appear/disappear (fade in/out) duration
static float GOptNoteSpeedMul = 1.0f; // >1 = faster note changes ("disco" mode)

// ---- debug options (off/neutral by default; normal behavior is unchanged
// unless explicitly turned on in the launch menu) ----
static int   GOptPhysics   = 0;     // entities collide and bounce off each other
static int   GOptLiveAudio = 0;     // continuously push pitch/volume instead of only at note-change
static int   GOptNoise     = 1;     // background noise grain on/off
static float GOptMotionSpeed = 1.0f; // 0.1-5.0, scales only entity movement/animation, not spawn pacing
static int   GOptHud = 0;           // on-screen FPS/pattern/voice/resolution bar

// ---- NEW: launch-time window size + mute options (CLI only, nothing
// above this line was touched) ----
static int   GOptWinW = 0;          // 0 = use the existing default (960)
static int   GOptWinH = 0;          // 0 = use the existing default (540)
static int   GOptMute = 0;          // --silent/-s: audio output is silenced
                                     // (unrelated to the existing GOptSilent
                                     // above, which controls the generative
                                     // "quiet phase" pacing, not audio)

// ------------------------- RNG -------------------------
static uint32_t RngState;
static inline uint32_t Xr(void) {
    uint32_t X = RngState;
    X ^= X << 13; X ^= X >> 17; X ^= X << 5;
    return (RngState = X);
}
static inline float Frand(void) { return (Xr() & 0xFFFFFF) / 16777215.0f; }
static inline int   Rrange(int a, int b) { return a + (int)(Frand() * (float)(b - a + 1)); }
static inline float Frange(float a, float b) { return a + Frand() * (b - a); }
// cubic bias helper — most values very small
static inline float Fsmall(void) { float U = Frand(); return U*U*U; }

// ------------------------- wobble -------------------------
static inline float Wobx(float X, float Y) {
    if (GWa1 <= 0.001f) return 0.0f;
    float U = X * 0.013f + Y * 0.017f;
    return sinf(GPt * GWf1 + U) * GWa1;
}
static inline float Woby(float X, float Y) {
    if (GWa2 <= 0.001f) return 0.0f;
    float U = X * 0.013f + Y * 0.017f;
    return cosf(GPt * GWf2 + U * 1.31f) * GWa2;
}

// ------------------------- pixel layer -------------------------
// v4-style blending: soft per-pixel attenuation, no drop.
// Combined with composite's -4 decay and NOT clearing fg_int each frame,
// this gives a subtle motion-blur/trail effect on moving shapes.
static inline void Plot(int X, int Y, int Color, uint8_t Iv) {
    if ((unsigned)X >= (unsigned)BufW || (unsigned)Y >= (unsigned)BufH) return;

    uint32_t H = (uint32_t)X * 374761393u
               + (uint32_t)Y * 668265263u
               + GSeed;
    H = (H ^ (H >> 13)) * 1274126177u;
    H ^= H >> 16;

    if (GPresence < 0.99f) {
        float r = (H & 0xFFFF) / 65535.0f;
        if (r > GPresence) return;
    }

    if (GBlend > 0.0f) {
        uint32_t H2 = H ^ GBlendSeed;
        H2 = (H2 ^ (H2 >> 15)) * 2246822519u;
        H2 ^= H2 >> 13;
        float R2 = (H2 & 0xFF) / 255.0f;
        Iv = (uint8_t)((float)Iv * (1.0f - GBlend * R2));
        if (Iv < 4) return;
    }

    int I = Y * BufW + X;
    if (Iv > FgInt[I]) { FgInt[I] = Iv; FgCol[I] = (uint16_t)Color; }
}

static inline void PlotW(int X, int Y, int Color, uint8_t Iv) {
    int Wx = X + (int)Wobx((float)X, (float)Y);
    int Wy = Y + (int)Woby((float)X, (float)Y);
    Plot(Wx, Wy, Color, Iv);
}

static void DrawLine(float X0, float Y0, float X1, float Y1,
                      int T, int Col, uint8_t Iv) {
    float Dx = X1 - X0, Dy = Y1 - Y0;
    float Len = sqrtf(Dx*Dx + Dy*Dy);
    if (Len < 0.5f) return;

    int Subs = 1;
    if (Len > 10.0f) Subs = (int)(Len / 10.0f) + 1;
    if (Subs > 48) Subs = 48;

    for (int K = 0; K < Subs; K++) {
        float U0 = (float)K / Subs;
        float U1 = (float)(K + 1) / Subs;
        float Sx = X0 + Dx * U0, Sy = Y0 + Dy * U0;
        float Ex = X0 + Dx * U1, Ey = Y0 + Dy * U1;
        Sx += Wobx(Sx, Sy); Sy += Woby(Sx, Sy);
        Ex += Wobx(Ex, Ey); Ey += Woby(Ex, Ey);

        float Sdx = Ex - Sx, Sdy = Ey - Sy;
        float Slen = sqrtf(Sdx*Sdx + Sdy*Sdy);
        int Steps = (int)Slen + 1;
        if (Steps < 1) Steps = 1;
        for (int I = 0; I <= Steps; I++) {
            float Uu = (float)I / Steps;
            int Px = (int)(Sx + Sdx*Uu + 0.5f);
            int Py = (int)(Sy + Sdy*Uu + 0.5f);
            if (T <= 0) {
                Plot(Px, Py, Col, Iv);
            } else {
                for (int Dy2 = -T; Dy2 <= T; Dy2++)
                    for (int Dx2 = -T; Dx2 <= T; Dx2++)
                        if (Dx2*Dx2 + Dy2*Dy2 <= T*T)
                            Plot(Px+Dx2, Py+Dy2, Col, Iv);
            }
        }
    }
}

// ------------------------- pattern types -------------------------
enum {
    PSuperformula = 0,
    PSpirograph, PSnake, PLissajous, PFourier, PMesh,
    PSpiral, PConstellation, PRosette, PMultiSpiro,
    PBend, PStretch, PBlob, PDots, PBezier, PWaves,
    PPolyline, PCurl,
    PTriangle, PHex, PCross, PAmoeba, PManyCircles,
    PConcentric, PGridDots, PScatter, PDna, PRipple,
    PPetal, PMoon, PArcFan,
    PSine, PZigzag, PCardioid, PLemniscate, PBranch, PTriFan,
    PWorm, POrbit, PBurst, PSpike, PGlow, PKnot,
    PDot, PSegment, PRing,
    PCount
};

typedef struct {
    int      Type;
    float    X, Y, Vx, Vy;
    float    Accel, MaxSpeed;
    int      WanderOn;
    float    Angle, Spin;
    float    Size, SizeBase, SizePulse, SizePulseT;
    int      Color;
    float    Life;
    float    Presence;
    int      Phase;
    float    InDur, HoldDur, OutDur;
    uint32_t Seed;
    int      Key;
    float    Velocity;
    float    RetrigTimer;
    int      Thickness;
    float    Blend;
    float    PatternT;
    int      WobbleOn;
    float    AnimF1, AnimF2, AnimA1, AnimA2;
    float    AnimF1Vel, AnimF2Vel;
    int      NotePlaying;
    float    P[32];
    float    PBase[32];
    float    PVel[32];
    int      Ip[32];
    int      WillMorph;
    float    BodyX[MaxBody];
    float    BodyY[MaxBody];
    int      BodyLen;
    float    Heading, HeadingVel;
} Entity;

static Entity Ents[MaxEnt];

// ------------------------- scale / notes -------------------------
static void PickScale(void) {
    static const int Scales[5][7] = {
        {0, 2, 4, 5, 7, 9, 11},
        {0, 2, 3, 5, 7, 8, 10},
        {0, 2, 3, 5, 7, 9, 10},
        {0, 3, 5, 7, 10, -1, -1},
        {0, 2, 4, 6, 8, 10, -1},
    };
    int Which = (int)(Xr() % 5);
    for (int I = 0; I < 7; I++) GScale[I] = Scales[Which][I];
    GScaleSize = (Which == 3) ? 5 : (Which == 4 ? 6 : 7);
    GRoot = 36 + (int)(Xr() % 12);
}
static int PickNoteBiased(int Steps) {
    int Idx = (int)(Xr() % (uint32_t)GScaleSize);
    int Oct = 1 + (int)(Xr() % 2);
    if (Steps > 0)      Idx = (Idx + Steps) % GScaleSize;
    else if (Steps < 0) Idx = (Idx + Steps + GScaleSize) % GScaleSize;
    int Note = GRoot + GScale[Idx] + 12 * Oct;
    if (Note > 100) Note = 100;
    if (Note < 24)  Note = 24;
    return Note;
}
static inline int PickNote(void) { return PickNoteBiased(0); }

// ------------------------- pattern parameter rolling -------------------------
static void RollPattern(Entity *E) {
    E->Type = Rrange(0, PCount - 1);
    E->Seed = Xr();
    memset(E->P,  0, sizeof(E->P));
    memset(E->Ip, 0, sizeof(E->Ip));

    switch (E->Type) {
    case PSuperformula:
        E->Ip[0]=Rrange(1,12); E->P[0]=Frange(.4f,1.6f); E->P[1]=Frange(.4f,1.6f);
        E->P[2]=Frange(1.f,5.f); E->P[3]=Frange(.5f,5.f); E->P[4]=Frange(.5f,5.f);
        break;
    case PSpirograph:
        E->Ip[0]=Rrange(4,14); E->Ip[1]=Rrange(1,E->Ip[0]-1); E->P[0]=Frange(.4f,1.f);
        break;
    case PSnake:
        E->Ip[0]=Rrange(40,160); E->P[0]=Frange(.1f,.7f); E->P[1]=Frange(.015f,.06f);
        break;
    case PLissajous:
        E->Ip[0]=Rrange(1,7); E->Ip[1]=Rrange(1,7); E->P[0]=Frange(0.f,6.28f);
        break;
    case PFourier:
        E->Ip[0]=Rrange(2,5);
        for (int I=0;I<E->Ip[0];I++){
            E->P[I*2]=Frange(.15f,1.f); E->P[I*2+1]=Frange(0.f,6.28f);
            E->Ip[1+I]=Rrange(1,8);
        } break;
    case PMesh:
        E->P[0]=Frange(.4f,1.f); E->P[1]=Frange(.4f,1.f);
        E->P[2]=Frange(.4f,1.f); E->P[3]=Frange(0.f,6.28f);
        break;
    case PSpiral:
        E->Ip[0]=Rrange(2,7); E->P[0]=Frange(.2f,.9f); E->P[1]=(Xr()&1)?1.f:-1.f;
        break;
    case PConstellation:
        E->Ip[0]=Rrange(5,12);
        for (int I=0;I<E->Ip[0];I++){
            float A2=Frange(0.f,6.283f), R2=Frange(.25f,1.f);
            E->P[I*2]=cosf(A2)*R2; E->P[I*2+1]=sinf(A2)*R2;
        } break;
    case PRosette:
        E->Ip[0]=Rrange(3,10); E->Ip[1]=Rrange(2,5); E->P[0]=Frange(.3f,.8f);
        break;
    case PMultiSpiro:
        E->Ip[0]=Rrange(4,12); E->Ip[1]=Rrange(1,E->Ip[0]-1);
        E->P[0]=Frange(.4f,1.f); E->Ip[2]=Rrange(2,5);
        break;
    case PBend:
        E->P[0]=Frange(0.f,6.28f); E->P[1]=Frange(1.5f,4.5f);
        E->P[2]=Frange(-1.5f,1.5f); E->P[3]=Frange(-1.5f,1.5f);
        break;
    case PStretch:
        E->P[0]=Frange(.5f,1.f); E->P[1]=Frange(.15f,.5f); E->P[2]=Frange(.3f,1.2f);
        break;
    case PBlob:
        E->Ip[0]=Rrange(150,500); E->P[0]=Frange(.6f,1.4f);
        break;
    case PDots:      E->Ip[0]=Rrange(4,16); break;
    case PBezier:
        E->P[0]=Frange(0.f,6.28f); E->P[1]=Frange(2.f,5.f);
        E->P[2]=Frange(-1.5f,1.5f); E->P[3]=Frange(-1.5f,1.5f);
        E->P[4]=Frange(-1.5f,1.5f); E->P[5]=Frange(-1.5f,1.5f);
        break;
    case PWaves:
        E->Ip[0]=Rrange(2,6); E->P[0]=Frange(.5f,3.f); E->P[1]=Frange(.1f,.3f);
        break;
    case PPolyline:  E->Ip[0]=Rrange(4,12); break;
    case PCurl:
        E->Ip[0]=Rrange(2,6); E->P[0]=Frange(1.f,3.f);
        break;
    case PTriangle:  E->P[0]=Frange(.6f,1.f); break;
    case PHex:       E->Ip[0]=Rrange(3,8); break;
    case PCross:
        E->P[0]=Frange(.3f,1.f); E->P[1]=Frange(.3f,1.f); E->Ip[0]=(Xr()&1);
        break;
    case PAmoeba:
        E->Ip[0]=Rrange(2,5);
        for (int I=0;I<E->Ip[0];I++){
            E->P[I*2]=Frange(.1f,.45f); E->P[I*2+1]=Frange(0.f,6.28f);
            E->Ip[1+I]=Rrange(2,7);
        } break;
    case PManyCircles:
        E->Ip[0]=Rrange(3,10); E->P[0]=Frange(.04f,.18f);
        break;
    case PConcentric:
        E->Ip[0]=Rrange(3,9); E->Ip[1]=(Xr()&1)?4:24;
        break;
    case PGridDots: E->Ip[0]=Rrange(3,9); break;
    case PScatter:
        E->Ip[0]=Rrange(6,24); E->P[0]=Frange(.05f,.2f);
        break;
    case PDna:
        E->Ip[0]=Rrange(2,6); E->P[0]=Frange(.2f,.45f);
        break;
    case PRipple:
        E->Ip[0]=Rrange(3,7); E->P[0]=Frange(.4f,1.4f);
        break;
    case PPetal:     E->Ip[0]=Rrange(2,7); break;
    case PMoon:
        E->P[0]=Frange(.55f,.9f); E->P[1]=Frange(.3f,.7f);
        break;
    case PArcFan:
        E->Ip[0]=Rrange(4,12); E->P[0]=Frange(.2f,.7f);
        break;
    case PSine:
        E->Ip[0]=Rrange(1,4); E->P[0]=Frange(.5f,3.f); E->P[1]=Frange(.1f,.35f);
        break;
    case PZigzag:
        E->Ip[0]=Rrange(4,20); E->P[0]=Frange(.15f,.7f);
        break;
    case PCardioid:   E->P[0]=Frange(-1.5f,-0.5f); break;
    case PLemniscate: E->Ip[0]=Rrange(1,4); break;
    case PBranch:
        E->Ip[0]=Rrange(3,7); E->Ip[1]=Rrange(2,4);
        break;
    case PTriFan:   E->Ip[0]=Rrange(4,14); break;
    case PWorm:
        E->BodyLen = Rrange(10, MaxBody - 1);
        E->Ip[0]    = E->BodyLen;
        E->P[0]     = Frange(0.03f, 0.06f);
        E->P[1]     = Frange(0.5f, 2.5f);
        E->P[2]     = Frange(0.5f, 1.8f);
        E->Heading     = Frange(0.f, 6.2831853f);
        E->HeadingVel = Frange(-0.6f, 0.6f);
        for (int I = 0; I < E->BodyLen; I++) {
            E->BodyX[I] = E->X;
            E->BodyY[I] = E->Y;
        }
        break;
    case POrbit:
        E->Ip[0] = Rrange(3, 10);
        E->P[0]  = Frange(0.4f, 1.6f) * ((Xr() & 1) ? 1.0f : -1.0f);
        E->P[1]  = Frange(0.3f, 1.2f);
        E->P[2]  = Frange(0.04f, 0.14f);
        break;
    case PBurst:
        E->Ip[0] = Rrange(8, 22);
        E->P[0]  = Frange(0.4f, 1.6f);
        E->P[1]  = Frange(2.0f, 6.0f);
        E->P[2]  = Frange(0.f, 6.28f);
        break;
    case PSpike:
        E->Ip[0] = Rrange(6, 18);
        E->P[0]  = Frange(0.3f, 1.2f);
        E->P[1]  = Frange(0.4f, 0.9f);
        break;
    case PGlow:
        E->Ip[0] = Rrange(60, 200);
        E->P[0]  = Frange(0.6f, 1.6f);
        E->P[1]  = Frange(0.2f, 0.9f);
        break;
    case PKnot:
        E->Ip[0] = Rrange(2, 5);
        E->Ip[1] = Rrange(2, 5);
        E->P[0]  = Frange(0.6f, 1.2f);
        break;
    case PDot:
        // cheapest possible pattern: a single pulsing point at the center.
        break;
    case PSegment:
        // a single straight stroke through the center, along e->angle.
        E->P[0] = Frange(0.5f, 1.0f);
        break;
    case PRing:
        // a single plain circle outline.
        E->Ip[0] = Rrange(40, 80);
        break;
    }

    for (int K = 0; K < 32; K++) {
        E->PBase[K] = E->P[K];
        float Mag = 0.5f + fabsf(E->P[K]);
        E->PVel[K] = Frange(-1.0f, 1.0f) * 0.05f * Mag;
    }
}

// ------------------------- rendering -------------------------
static void RenderEntity(Entity *E) {
    GPresence   = E->Presence;
    GSeed       = E->Seed;
    GBlendSeed = E->Seed ^ 0x5A5A5A5Au;
    GPt  = E->PatternT;
    GWf1 = E->AnimF1; GWf2 = E->AnimF2;
    GWa1 = E->AnimA1; GWa2 = E->AnimA2;

    float S  = E->Size;
    float Cx = E->X, Cy = E->Y;
    float a  = E->Angle;
    int   Col = E->Color;

    int T = (int)((float)E->Thickness * E->Presence + 0.5f);

    float SizeFactor = S / (BufH * 0.45f);
    if (SizeFactor > 1.0f) SizeFactor = 1.0f;
    float ThickFactor = E->Thickness / 2.0f;
    float BrightFactor = SizeFactor * (0.7f + 0.3f * ThickFactor);
    float BaseB = 40.0f + 215.0f * BrightFactor;
    uint8_t Iv = (uint8_t)(BaseB * E->Presence);
    if (Iv < 6 && E->Presence > 0.01f) Iv = 6;

    // v4-style blend amount (dim patterns blend less)
    GBlend = E->Blend * (0.35f + 0.65f * BrightFactor) * GOptBlend;

    int Steps;
    switch (E->Type) {

    case PSuperformula: {
        Steps=420; int M=E->Ip[0];
        float Aa=E->P[0],Bb=E->P[1],N1=E->P[2],N2=E->P[3],N3=E->P[4];
        float Px=0,Py=0;
        for(int I=0;I<=Steps;I++){
            float Th=(float)I/Steps*6.2831853f;
            float C1=cosf(M*Th/4.f)/Aa,C2=sinf(M*Th/4.f)/Bb;
            float T1=powf(fabsf(C1),N2),T2=powf(fabsf(C2),N3);
            float r=powf(T1+T2,-1.f/N1);
            if(!isfinite(r)||r>5.f) r=5.f;
            float Nx=cosf(Th+a)*r*S*0.4f+Cx;
            float Ny=sinf(Th+a)*r*S*0.4f+Cy;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PSpirograph: {
        int R=E->Ip[0],r=E->Ip[1];
        float D=E->P[0]*(float)r;
        int Ra=R,Rb=r;
        while(Rb){int Tmp=Ra%Rb;Ra=Rb;Rb=Tmp;}
        float G=(float)Ra;
        float Tmax=6.2831853f*(float)r/G;
        Steps=500; float Sc=S*0.4f/(float)R;
        float Px=0,Py=0;
        for(int I=0;I<=Steps;I++){
            float Th=(float)I/Steps*Tmax;
            float Nx=(R-r)*cosf(Th)+D*cosf((R-r)/(float)r*Th);
            float Ny=(R-r)*sinf(Th)-D*sinf((R-r)/(float)r*Th);
            float Fx=Cx+(cosf(a)*Nx-sinf(a)*Ny)*Sc;
            float Fy=Cy+(sinf(a)*Nx+cosf(a)*Ny)*Sc;
            if(I>0) DrawLine(Px,Py,Fx,Fy,T,Col,Iv);
            Px=Fx;Py=Fy;
        }
    } break;
    case PSnake: {
        int Segs=E->Ip[0]; float Turn=E->P[0], Stp=E->P[1]*S;
        float Px=Cx-S*0.5f, Py=Cy;
        float Dir=Frange(0.f,6.2831853f);
        uint32_t St=E->Seed;
        for(int I=0;I<Segs;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float r=((St&0xFFFF)/65535.f)-0.5f;
            Dir+=r*Turn*2.f;
            float Nx=Px+cosf(Dir)*Stp, Ny=Py+sinf(Dir)*Stp;
            DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PLissajous: {
        Steps=420; float A=(float)E->Ip[0],B=(float)E->Ip[1],D=E->P[0];
        float Px=0,Py=0;
        for(int I=0;I<=Steps;I++){
            float Th=(float)I/Steps*6.2831853f;
            float Nx=sinf(A*Th+D), Ny=sinf(B*Th);
            float Fx=Cx+(cosf(a)*Nx-sinf(a)*Ny)*S*0.5f;
            float Fy=Cy+(sinf(a)*Nx+cosf(a)*Ny)*S*0.5f;
            if(I>0) DrawLine(Px,Py,Fx,Fy,T,Col,Iv);
            Px=Fx;Py=Fy;
        }
    } break;
    case PFourier: {
        Steps=420; int Nt=E->Ip[0]; float Px=0,Py=0;
        for(int I=0;I<=Steps;I++){
            float Th=(float)I/Steps*6.2831853f; float r=1.f;
            for(int K=0;K<Nt;K++)
                r += E->P[K*2]*cosf(E->Ip[1+K]*Th+E->P[K*2+1]);
            r*=0.5f; if(r<0.05f) r=0.05f;
            float Nx=cosf(Th+a)*r*S*0.5f+Cx;
            float Ny=sinf(Th+a)*r*S*0.5f+Cy;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PMesh: {
        float Sx=E->P[0],Sy=E->P[1],Sz=E->P[2];
        float Tilt=E->P[3] + E->PatternT*0.25f;
        float Verts[8][3]={{-Sx,-Sy,-Sz},{Sx,-Sy,-Sz},{Sx,Sy,-Sz},{-Sx,Sy,-Sz},
                           {-Sx,-Sy,Sz},{Sx,-Sy,Sz},{Sx,Sy,Sz},{-Sx,Sy,Sz}};
        float Ca=cosf(a),Sa=sinf(a),Cb=cosf(Tilt),Sb=sinf(Tilt);
        for(int I=0;I<8;I++){
            float X=Verts[I][0],Y=Verts[I][1],Z=Verts[I][2];
            float X1=Ca*X+Sa*Z, Z1=-Sa*X+Ca*Z;
            float Y1=Cb*Y-Sb*Z1, Z2=Sb*Y+Cb*Z1;
            float D=3.f; float Persp=D/(D+Z2);
            Verts[I][0]=Cx+X1*S*0.5f*Persp;
            Verts[I][1]=Cy+Y1*S*0.5f*Persp;
        }
        int Ed[12][2]={{0,1},{1,2},{2,3},{3,0},{4,5},{5,6},{6,7},{7,4},
                       {0,4},{1,5},{2,6},{3,7}};
        for(int I=0;I<12;I++)
            DrawLine(Verts[Ed[I][0]][0],Verts[Ed[I][0]][1],
                      Verts[Ed[I][1]][0],Verts[Ed[I][1]][1],T,Col,Iv);
    } break;
    case PSpiral: {
        int Turns=E->Ip[0];
        float Growth=E->P[0], Dir=E->P[1];
        Steps=320; float Total=(float)Turns*6.2831853f;
        float Px=0,Py=0;
        for(int I=0;I<=Steps;I++){
            float U=(float)I/Steps;
            float Th=U*Total*Dir;
            float r=powf(U,Growth);
            float Nx=cosf(Th+a)*r*S*0.5f+Cx;
            float Ny=sinf(Th+a)*r*S*0.5f+Cy;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PConstellation: {
        int n=E->Ip[0]; float Pts[24][2];
        for(int I=0;I<n;I++){
            float Px=E->P[I*2]*S*0.5f, Py=E->P[I*2+1]*S*0.5f;
            float Fx=Cx+cosf(a)*Px-sinf(a)*Py;
            float Fy=Cy+sinf(a)*Px+cosf(a)*Py;
            Fx += Wobx(Fx,Fy); Fy += Woby(Fx,Fy);
            Pts[I][0]=Fx; Pts[I][1]=Fy;
        }
        int Rd=T+1;
        for(int I=0;I<n;I++)
            for(int Dy2=-Rd;Dy2<=Rd;Dy2++)
                for(int Dx2=-Rd;Dx2<=Rd;Dx2++)
                    if(Dx2*Dx2+Dy2*Dy2<=Rd*Rd)
                        Plot((int)Pts[I][0]+Dx2,(int)Pts[I][1]+Dy2,Col,Iv);
        for(int I=0;I<n;I++){
            int Best=-1; float Bd=1e9f;
            for(int J=0;J<n;J++){
                if(J==I) continue;
                float Dx=Pts[I][0]-Pts[J][0], Dy=Pts[I][1]-Pts[J][1];
                float D2=Dx*Dx+Dy*Dy;
                if(D2<Bd){Bd=D2;Best=J;}
            }
            if(Best>=0&&Best!=I)
                DrawLine(Pts[I][0],Pts[I][1],Pts[Best][0],Pts[Best][1],T,Col,Iv);
        }
    } break;
    case PRosette: {
        int Petals=E->Ip[0], Layers=E->Ip[1]; float Inner=E->P[0];
        for(int L=0;L<Layers;L++){
            float ROut=S*0.5f*(1.f-(float)L/Layers*0.3f);
            float RIn=ROut*Inner;
            int St=Petals*2;
            for(int I=0;I<St;I++){
                float Th0=(float)I/St*6.2831853f+a+(float)L*0.3f;
                float Th1=(float)(I+1)/St*6.2831853f+a+(float)L*0.3f;
                float Rr0=(I&1)?ROut:RIn, Rr1=((I+1)&1)?ROut:RIn;
                DrawLine(Cx+cosf(Th0)*Rr0,Cy+sinf(Th0)*Rr0,
                          Cx+cosf(Th1)*Rr1,Cy+sinf(Th1)*Rr1,T,Col,Iv);
            }
        }
    } break;
    case PMultiSpiro: {
        int R=E->Ip[0], r=E->Ip[1];
        float D=E->P[0]*(float)r;
        int Copies=E->Ip[2];
        int Ra=R,Rb=r;
        while(Rb){int Tmp=Ra%Rb;Ra=Rb;Rb=Tmp;}
        float G=(float)Ra;
        float Tmax=6.2831853f*(float)r/G;
        Steps=400; float Sc=S*0.4f/(float)R;
        for(int C=0;C<Copies;C++){
            float Offset=(float)C/Copies*6.2831853f+a;
            float Px=0,Py=0;
            for(int I=0;I<=Steps;I++){
                float Th=(float)I/Steps*Tmax;
                float Nx=(R-r)*cosf(Th)+D*cosf((R-r)/(float)r*Th);
                float Ny=(R-r)*sinf(Th)-D*sinf((R-r)/(float)r*Th);
                float Fx=Cx+(cosf(Offset)*Nx-sinf(Offset)*Ny)*Sc;
                float Fy=Cy+(sinf(Offset)*Nx+cosf(Offset)*Ny)*Sc;
                if(I>0) DrawLine(Px,Py,Fx,Fy,T,Col,Iv);
                Px=Fx;Py=Fy;
            }
        }
    } break;
    case PBend: {
        float Ang0=E->P[0]; float Ang1=Ang0+E->P[1];
        float P0x=Cx+cosf(Ang0)*S*0.5f, P0y=Cy+sinf(Ang0)*S*0.5f;
        float P2x=Cx+cosf(Ang1)*S*0.5f, P2y=Cy+sinf(Ang1)*S*0.5f;
        float C1x=Cx+E->P[2]*S*0.5f, C1y=Cy+E->P[3]*S*0.5f;
        Steps=80; float Px=P0x, Py=P0y;
        for(int I=1;I<=Steps;I++){
            float U=(float)I/Steps, Mu=1.f-U;
            float Bx=Mu*Mu*P0x+2.f*Mu*U*C1x+U*U*P2x;
            float By=Mu*Mu*P0y+2.f*Mu*U*C1y+U*U*P2y;
            DrawLine(Px,Py,Bx,By,T,Col,Iv);
            Px=Bx;Py=By;
        }
    } break;
    case PStretch: {
        float Rx0=E->P[0]*S*0.5f, Ry0=E->P[1]*S*0.5f;
        float St=1.f+0.8f*sinf(E->SizePulseT*E->P[2]);
        float Rx=Rx0*St, Ry=Ry0/St;
        int Segs=64; float Px=0,Py=0;
        for(int I=0;I<=Segs;I++){
            float Th=(float)I/Segs*6.2831853f;
            float Ex=cosf(Th)*Rx, Ey=sinf(Th)*Ry;
            float Fx=Cx+cosf(a)*Ex-sinf(a)*Ey;
            float Fy=Cy+sinf(a)*Ex+cosf(a)*Ey;
            if(I>0) DrawLine(Px,Py,Fx,Fy,T,Col,Iv);
            Px=Fx;Py=Fy;
        }
    } break;
    case PBlob: {
        int Nd=E->Ip[0]; float Fall=E->P[0];
        uint32_t St=E->Seed; int Rd=T;
        for(int I=0;I<Nd;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U1=(St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U2=(St&0xFFFF)/65535.f;
            float r=powf(U1,Fall)*S*0.5f, Th=U2*6.2831853f;
            int Px=(int)(Cx+cosf(Th)*r+0.5f);
            int Py=(int)(Cy+sinf(Th)*r+0.5f);
            if(Rd<=0) PlotW(Px,Py,Col,Iv);
            else for(int Dy2=-Rd;Dy2<=Rd;Dy2++)
                    for(int Dx2=-Rd;Dx2<=Rd;Dx2++)
                        if(Dx2*Dx2+Dy2*Dy2<=Rd*Rd)
                            PlotW(Px+Dx2,Py+Dy2,Col,Iv);
        }
    } break;
    case PDots: {
        int n=E->Ip[0]; uint32_t St=E->Seed; int Rd=T;
        for(int I=0;I<n;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float Dx=((St&0xFFFF)/65535.f-0.5f)*S;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float Dy=((St&0xFFFF)/65535.f-0.5f)*S;
            int Px=(int)(Cx+Dx+0.5f), Py=(int)(Cy+Dy+0.5f);
            if(Rd<=0) PlotW(Px,Py,Col,Iv);
            else for(int Dy2=-Rd;Dy2<=Rd;Dy2++)
                    for(int Dx2=-Rd;Dx2<=Rd;Dx2++)
                        if(Dx2*Dx2+Dy2*Dy2<=Rd*Rd)
                            PlotW(Px+Dx2,Py+Dy2,Col,Iv);
        }
    } break;
    case PBezier: {
        float Ang0=E->P[0]; float Ang1=Ang0+E->P[1];
        float P0x=Cx+cosf(Ang0)*S*0.5f, P0y=Cy+sinf(Ang0)*S*0.5f;
        float P3x=Cx+cosf(Ang1)*S*0.5f, P3y=Cy+sinf(Ang1)*S*0.5f;
        float C1x=Cx+E->P[2]*S*0.5f, C1y=Cy+E->P[3]*S*0.5f;
        float C2x=Cx+E->P[4]*S*0.5f, C2y=Cy+E->P[5]*S*0.5f;
        Steps=90; float Px=P0x, Py=P0y;
        for(int I=1;I<=Steps;I++){
            float U=(float)I/Steps, Mu=1.f-U;
            float Bx=Mu*Mu*Mu*P0x+3*Mu*Mu*U*C1x+3*Mu*U*U*C2x+U*U*U*P3x;
            float By=Mu*Mu*Mu*P0y+3*Mu*Mu*U*C1y+3*Mu*U*U*C2y+U*U*U*P3y;
            DrawLine(Px,Py,Bx,By,T,Col,Iv);
            Px=Bx;Py=By;
        }
    } break;
    case PWaves: {
        int Nw=E->Ip[0]; float freq=E->P[0], Amp=E->P[1]*S;
        float Spacing=S/(float)(Nw+1);
        for(int W=0;W<Nw;W++){
            float By=Cy-S*0.5f+Spacing*(float)(W+1);
            float Px=Cx-S*0.5f;
            float Py=By+sinf((Px-Cx)/S*freq*6.2831853f+a)*Amp;
            int N=60;
            for(int I=1;I<=N;I++){
                float U=(float)I/N;
                float X=Cx-S*0.5f+U*S;
                float Y=By+sinf((X-Cx)/S*freq*6.2831853f+a)*Amp;
                DrawLine(Px,Py,X,Y,T,Col,Iv);
                Px=X;Py=Y;
            }
        }
    } break;
    case PPolyline: {
        int n=E->Ip[0]; float Vx[16],Vy[16];
        uint32_t St=E->Seed;
        for(int I=0;I<=n;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U1=(St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U2=(St&0xFFFF)/65535.f;
            float Fx=(U1-0.5f)*S, Fy=(U2-0.5f)*S;
            Vx[I]=Cx+cosf(a)*Fx-sinf(a)*Fy;
            Vy[I]=Cy+sinf(a)*Fx+cosf(a)*Fy;
        }
        for(int I=0;I<n;I++)
            DrawLine(Vx[I],Vy[I],Vx[I+1],Vy[I+1],T,Col,Iv);
    } break;
    case PCurl: {
        int Narms=E->Ip[0]; float Turns=E->P[0];
        for(int K=0;K<Narms;K++){
            float Off=(float)K/Narms*6.2831853f;
            int N=200; float Px=Cx,Py=Cy;
            for(int I=1;I<=N;I++){
                float U=(float)I/N;
                float Th=U*Turns*6.2831853f+Off+a;
                float r=U*S*0.5f;
                float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
                DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
                Px=Nx;Py=Ny;
            }
        }
    } break;
    case PTriangle: {
        float r=S*0.5f, D0=E->P[0]*0.4f;
        float A0=a, A1=A0+2.094f+Frange(-D0,D0), A2=A1+2.094f+Frange(-D0,D0);
        DrawLine(Cx+cosf(A0)*r,Cy+sinf(A0)*r,Cx+cosf(A1)*r,Cy+sinf(A1)*r,T,Col,Iv);
        DrawLine(Cx+cosf(A1)*r,Cy+sinf(A1)*r,Cx+cosf(A2)*r,Cy+sinf(A2)*r,T,Col,Iv);
        DrawLine(Cx+cosf(A2)*r,Cy+sinf(A2)*r,Cx+cosf(A0)*r,Cy+sinf(A0)*r,T,Col,Iv);
    } break;
    case PHex: {
        int n=E->Ip[0]; float r=S*0.5f;
        float Prevx=0,Prevy=0;
        for(int I=0;I<=n;I++){
            float Th=(float)(I%n)/n*6.2831853f+a;
            float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
            if(I>0) DrawLine(Prevx,Prevy,Nx,Ny,T,Col,Iv);
            Prevx=Nx;Prevy=Ny;
        }
    } break;
    case PCross: {
        float Ax=S*0.5f*E->P[0], Ay=S*0.5f*E->P[1];
        DrawLine(Cx-Ax,Cy,Cx+Ax,Cy,T,Col,Iv);
        DrawLine(Cx,Cy-Ay,Cx,Cy+Ay,T,Col,Iv);
        if(E->Ip[0]){
            DrawLine(Cx-Ax*0.7f,Cy-Ay*0.7f,Cx+Ax*0.7f,Cy+Ay*0.7f,T,Col,Iv);
            DrawLine(Cx-Ax*0.7f,Cy+Ay*0.7f,Cx+Ax*0.7f,Cy-Ay*0.7f,T,Col,Iv);
        }
    } break;
    case PAmoeba: {
        int Nt=E->Ip[0], Segs=72; float Px=0,Py=0;
        for(int I=0;I<=Segs;I++){
            float Th=(float)I/Segs*6.2831853f;
            float r=1.f;
            for(int K=0;K<Nt;K++)
                r += E->P[K*2]*cosf(E->Ip[1+K]*Th+E->P[K*2+1]);
            r*=0.5f; if(r<0.1f) r=0.1f;
            float Nx=Cx+cosf(Th+a)*r*S*0.5f;
            float Ny=Cy+sinf(Th+a)*r*S*0.5f;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PManyCircles: {
        int n=E->Ip[0]; float r=E->P[0]*S;
        uint32_t St=E->Seed;
        for(int I=0;I<n;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U1=(St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U2=(St&0xFFFF)/65535.f;
            float Px=Cx+(U1-0.5f)*S*0.8f, Py=Cy+(U2-0.5f)*S*0.8f;
            int Segs=16; float Ax=0,Ay=0;
            for(int J=0;J<=Segs;J++){
                float Th=(float)J/Segs*6.2831853f;
                float Nx=Px+cosf(Th)*r, Ny=Py+sinf(Th)*r;
                if(J>0) DrawLine(Ax,Ay,Nx,Ny,T,Col,Iv);
                Ax=Nx;Ay=Ny;
            }
        }
    } break;
    case PConcentric: {
        int n=E->Ip[0], Sides=E->Ip[1];
        float Rmax=S*0.5f;
        for(int K=1;K<=n;K++){
            float r=Rmax*(float)K/n; float Ax=0,Ay=0;
            for(int I=0;I<=Sides;I++){
                float Th=(float)(I%Sides)/Sides*6.2831853f+a;
                float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
                if(I>0) DrawLine(Ax,Ay,Nx,Ny,T,Col,Iv);
                Ax=Nx;Ay=Ny;
            }
        }
    } break;
    case PGridDots: {
        int n=E->Ip[0]; int Rd=T+1;
        float Stp=S/(float)(n-1);
        for(int I=0;I<n;I++)
            for(int J=0;J<n;J++){
                float Px=Cx-S*0.5f+I*Stp, Py=Cy-S*0.5f+J*Stp;
                for(int Dy=-Rd;Dy<=Rd;Dy++)
                    for(int Dx=-Rd;Dx<=Rd;Dx++)
                        if(Dx*Dx+Dy*Dy<=Rd*Rd)
                            PlotW((int)(Px+Dx+0.5f),(int)(Py+Dy+0.5f),Col,Iv);
            }
    } break;
    case PScatter: {
        int n=E->Ip[0]; float Dl=S*E->P[0];
        uint32_t St=E->Seed;
        for(int I=0;I<n;I++){
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U1=(St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U2=(St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U3=(St&0xFFFF)/65535.f;
            float Px=Cx+(U1-0.5f)*S, Py=Cy+(U2-0.5f)*S;
            float Da=U3*6.2831853f;
            DrawLine(Px,Py,Px+cosf(Da)*Dl,Py+sinf(Da)*Dl,T,Col,Iv);
        }
    } break;
    case PDna: {
        int Cyc=E->Ip[0]; float Amp=S*E->P[0];
        int N=60; float Px1=0,Py1=0,Px2=0,Py2=0;
        for(int I=0;I<=N;I++){
            float U=(float)I/N;
            float X=Cx-S*0.5f+U*S;
            float Y1=Cy+sinf(U*Cyc*6.2831853f+a)*Amp;
            float Y2=Cy+sinf(U*Cyc*6.2831853f+a+3.14159265f)*Amp;
            if(I>0){
                DrawLine(Px1,Py1,X,Y1,T,Col,Iv);
                DrawLine(Px2,Py2,X,Y2,T,Col,Iv);
            }
            if(I%5==0) DrawLine(X,Y1,X,Y2,T,Col,Iv);
            Px1=X;Py1=Y1;Px2=X;Py2=Y2;
        }
    } break;
    case PRipple: {
        int n=E->Ip[0]; float Sp=E->P[0];
        float Phase=fmodf(E->SizePulseT*Sp,1.f);
        for(int K=0;K<n;K++){
            float r=((float)K+Phase)/n*S*0.5f;
            int Segs=32; float Px=0,Py=0;
            for(int I=0;I<=Segs;I++){
                float Th=(float)I/Segs*6.2831853f;
                float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
                if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
                Px=Nx;Py=Ny;
            }
        }
    } break;
    case PPetal: {
        int K=E->Ip[0]; int N=240; float Px=0,Py=0;
        for(int I=0;I<=N;I++){
            float Th=(float)I/N*6.2831853f;
            float r=fabsf(cosf(K*Th*0.5f));
            float Nx=Cx+cosf(Th+a)*r*S*0.5f;
            float Ny=Cy+sinf(Th+a)*r*S*0.5f;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PMoon: {
        float r=S*0.5f, R2=r*E->P[0], D=r*E->P[1];
        int Segs=64; float Px=0,Py=0; int First=1;
        for(int I=0;I<=Segs;I++){
            float Th=(float)I/Segs*6.2831853f+a;
            float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
            float Dxc=Nx-(Cx+cosf(a)*D), Dyc=Ny-(Cy+sinf(a)*D);
            if(Dxc*Dxc+Dyc*Dyc>R2*R2){
                if(!First) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
                Px=Nx;Py=Ny;First=0;
            } else First=1;
        }
    } break;
    case PArcFan: {
        int n=E->Ip[0]; float r=S*0.5f, Arc=E->P[0]*3.14159265f;
        for(int K=0;K<n;K++){
            float St=a+(float)K/n*6.2831853f;
            int Segs=10; float Px=0,Py=0;
            for(int I=0;I<=Segs;I++){
                float Th=St+(float)I/Segs*Arc;
                float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
                if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
                Px=Nx;Py=Ny;
            }
        }
    } break;
    case PSine: {
        int Nw=E->Ip[0]; float freq=E->P[0], Amp=E->P[1]*S;
        float Spc=S/(float)(Nw+1);
        for(int W=0;W<Nw;W++){
            float By=Cy-S*0.5f+Spc*(float)(W+1);
            float Px=Cx-S*0.5f;
            float Py=By+sinf((Px-Cx)/S*freq*6.2831853f+a)*Amp;
            int N=80;
            for(int I=1;I<=N;I++){
                float U=(float)I/N;
                float X=Cx-S*0.5f+U*S;
                float Y=By+sinf((X-Cx)/S*freq*6.2831853f+a)*Amp;
                DrawLine(Px,Py,X,Y,T,Col,Iv);
                Px=X;Py=Y;
            }
        }
    } break;
    case PZigzag: {
        int n=E->Ip[0]; float Amp=E->P[0]*S*0.5f;
        float Prevx=Cx-S*0.5f, Prevy=Cy;
        for(int I=1;I<=n;I++){
            float U=(float)I/n;
            float X=Cx-S*0.5f+U*S;
            float Y=Cy+((I&1)?-1.f:1.f)*Amp*(0.5f+Frand()*0.5f);
            DrawLine(Prevx,Prevy,X,Y,T,Col,Iv);
            Prevx=X;Prevy=Y;
        }
    } break;
    case PCardioid: {
        int N=300; float K=E->P[0]; float Px=0,Py=0;
        for(int I=0;I<=N;I++){
            float Th=(float)I/N*6.2831853f;
            float r=(1.f+cosf(Th))*0.5f;
            r += K*0.15f*sinf(Th*3.f);
            if(r<0) r=0;
            float Nx=Cx+cosf(Th+a)*r*S*0.5f;
            float Ny=Cy+sinf(Th+a)*r*S*0.5f;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PLemniscate: {
        int N=280; int K=E->Ip[0]; float Px=0,Py=0;
        for(int I=0;I<=N;I++){
            float Th=(float)I/N*6.2831853f;
            float D=1.f+sinf(K*Th)*sinf(K*Th);
            float r=(D>0.01f)?(1.f/D):1.f;
            float Nx=Cx+cosf(Th+a)*r*S*0.35f;
            float Ny=Cy+sinf(Th+a)*r*S*0.35f;
            if(I>0) DrawLine(Px,Py,Nx,Ny,T,Col,Iv);
            Px=Nx;Py=Ny;
        }
    } break;
    case PBranch: {
        int Arms=E->Ip[0], Depth=E->Ip[1];
        for(int K=0;K<Arms;K++){
            float Ba=a+(float)K/Arms*6.2831853f;
            float X0=Cx,Y0=Cy, L=S*0.5f;
            for(int D=0;D<Depth;D++){
                float Ang=Ba+Frange(-0.6f,0.6f);
                float X1=X0+cosf(Ang)*L, Y1=Y0+sinf(Ang)*L;
                DrawLine(X0,Y0,X1,Y1,T,Col,Iv);
                float BAng=Ang+Frange(-0.8f,0.8f);
                float Bx=X1+cosf(BAng)*L*0.6f;
                float By=Y1+sinf(BAng)*L*0.6f;
                DrawLine(X1,Y1,Bx,By,T,Col,Iv);
                X0=X1;Y0=Y1;
                L*=0.6f;
            }
        }
    } break;
    case PTriFan: {
        int n=E->Ip[0]; float r=S*0.5f;
        for(int K=0;K<n;K++){
            float Th=a+(float)K/n*6.2831853f;
            float Nx=Cx+cosf(Th)*r, Ny=Cy+sinf(Th)*r;
            DrawLine(Cx,Cy,Nx,Ny,T,Col,Iv);
        }
    } break;
    case PWorm: {
        for (int I = 0; I < E->BodyLen - 1; I++) {
            DrawLine(E->BodyX[I], E->BodyY[I],
                      E->BodyX[I+1], E->BodyY[I+1], T, Col, Iv);
        }
        int Rd = T + 1;
        for (int Dy = -Rd; Dy <= Rd; Dy++)
            for (int Dx = -Rd; Dx <= Rd; Dx++)
                if (Dx*Dx + Dy*Dy <= Rd*Rd)
                    Plot((int)E->BodyX[0] + Dx, (int)E->BodyY[0] + Dy, Col, Iv);
    } break;
    case POrbit: {
        int n = E->Ip[0];
        float BaseR = S * 0.4f;
        for (int I = 0; I < n; I++) {
            float Phase = (float)I / n * 6.2831853f;
            float TOff = Phase + E->PatternT * E->P[0];
            float RrScale = 0.55f + 0.45f * sinf(E->PatternT * E->P[1] + I * 1.7f);
            float Rr = BaseR * RrScale;
            float Ox = Cx + cosf(TOff) * Rr;
            float Oy = Cy + sinf(TOff) * Rr;
            float Cr = S * E->P[2];
            int Segs = 12;
            float Px = 0, Py = 0;
            for (int J = 0; J <= Segs; J++) {
                float A1 = (float)J / Segs * 6.2831853f;
                float Nx = Ox + cosf(A1) * Cr;
                float Ny = Oy + sinf(A1) * Cr;
                if (J > 0) DrawLine(Px, Py, Nx, Ny, T, Col, Iv);
                Px = Nx; Py = Ny;
            }
        }
    } break;
    case PBurst: {
        int n = E->Ip[0];
        float Cyc = fmodf(E->PatternT * E->P[0], 1.0f);
        float Rad = S * 0.5f * (0.15f + 0.85f * sinf(Cyc * 3.14159265f));
        float DashPh = E->PatternT * E->P[1];
        for (int I = 0; I < n; I++) {
            float Th = (float)I / n * 6.2831853f + E->P[2];
            float Dsh = 0.35f + 0.65f * (0.5f + 0.5f * sinf(DashPh + I * 1.9f));
            float R1 = Rad * Dsh;
            DrawLine(Cx, Cy, Cx + cosf(Th) * R1, Cy + sinf(Th) * R1, T, Col, Iv);
        }
    } break;
    case PSpike: {
        int n = E->Ip[0];
        float Rmax = S * 0.5f;
        float Rmin = Rmax * E->P[1];
        float Ph = E->PatternT * E->P[0];
        for (int I = 0; I < n; I++) {
            float Th = (float)I / n * 6.2831853f + a;
            float W = 0.5f + 0.5f * sinf(Ph + I * 1.3f);
            float r = Rmin + (Rmax - Rmin) * W;
            DrawLine(Cx + cosf(Th)*Rmin, Cy + sinf(Th)*Rmin,
                      Cx + cosf(Th)*r,    Cy + sinf(Th)*r, T, Col, Iv);
        }
    } break;
    case PGlow: {
        int Nd = E->Ip[0];
        float Fall = E->P[0], Swirl = E->P[1];
        uint32_t St = E->Seed;
        int Rd = T;
        for (int I = 0; I < Nd; I++) {
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U1 = (St&0xFFFF)/65535.f;
            St^=St<<13;St^=St>>17;St^=St<<5;
            float U2 = (St&0xFFFF)/65535.f;
            float r = powf(U1, Fall) * S * 0.5f;
            float Th = U2 * 6.2831853f + E->PatternT * Swirl * (1.0f - r/(S*0.5f+0.01f));
            int Px = (int)(Cx + cosf(Th) * r + 0.5f);
            int Py = (int)(Cy + sinf(Th) * r + 0.5f);
            if (Rd <= 0) PlotW(Px, Py, Col, Iv);
            else for (int Dy2=-Rd; Dy2<=Rd; Dy2++)
                    for (int Dx2=-Rd; Dx2<=Rd; Dx2++)
                        if (Dx2*Dx2+Dy2*Dy2 <= Rd*Rd)
                            PlotW(Px+Dx2, Py+Dy2, Col, Iv);
        }
    } break;
    case PKnot: {
        int P = E->Ip[0], Q = E->Ip[1];
        float Bre = 1.0f + 0.4f * sinf(E->PatternT * E->P[0]);
        int N = 400;
        float Px=0, Py=0;
        for (int I = 0; I <= N; I++) {
            float U = (float)I / N * 6.2831853f;
            float r = Bre * (1.0f + 0.5f * cosf(Q * U));
            float Nx = cosf(P * U) * r;
            float Ny = sinf(P * U) * r;
            float Fx = Cx + (cosf(a)*Nx - sinf(a)*Ny) * S * 0.35f;
            float Fy = Cy + (sinf(a)*Nx + cosf(a)*Ny) * S * 0.35f;
            if (I > 0) DrawLine(Px, Py, Fx, Fy, T, Col, Iv);
            Px = Fx; Py = Fy;
        }
    } break;
    case PDot: {
        int Rd = T + (int)(S * 0.18f) + 1;
        for (int Dy = -Rd; Dy <= Rd; Dy++)
            for (int Dx = -Rd; Dx <= Rd; Dx++)
                if (Dx*Dx + Dy*Dy <= Rd*Rd)
                    Plot((int)Cx + Dx, (int)Cy + Dy, Col, Iv);
    } break;
    case PSegment: {
        float Half = S * 0.5f * E->P[0];
        float X0 = Cx - cosf(a) * Half, Y0 = Cy - sinf(a) * Half;
        float X1 = Cx + cosf(a) * Half, Y1 = Cy + sinf(a) * Half;
        DrawLine(X0, Y0, X1, Y1, T, Col, Iv);
    } break;
    case PRing: {
        int n = E->Ip[0]; float r = S * 0.5f;
        float Px = 0, Py = 0;
        for (int I = 0; I <= n; I++) {
            float Th = (float)I / n * 6.2831853f + a;
            float Nx = Cx + cosf(Th) * r, Ny = Cy + sinf(Th) * r;
            if (I > 0) DrawLine(Px, Py, Nx, Ny, T, Col, Iv);
            Px = Nx; Py = Ny;
        }
    } break;
    }
}

// ------------------------- lifecycle -------------------------
static void SpawnEntity(void) {
    for (int I = 0; I < MaxEnt; I++) {
        Entity *E = &Ents[I];
        if (E->Phase == -1) {
            memset(E, 0, sizeof(*E));
            E->X = Frange(BufW * 0.15f, BufW * 0.85f);
            E->Y = Frange(BufH * 0.15f, BufH * 0.85f);
            E->Vx = Frange(-15.f, 15.f);
            E->Vy = Frange(-15.f, 15.f);
            E->Angle = Frange(0.f, 6.2831853f);
            E->Spin  = Frange(-0.9f, 0.9f);

            // Most entities small, large ones rare: the exponent pulls U
            // toward 0 before it's mapped onto the size range.
            float U = Frand();
            U = powf(U, 2.5f);
            E->SizeBase = BufH * (0.02f + U * 0.58f);

            E->Size = E->SizeBase;

            // size pulse: strong pulsing is rare (2 / 10 / 86 / 2)
            int Pr = (int)(Xr() % 100);
            if (Pr < 2)       E->SizePulse = Frange(0.22f, 0.45f);
            else if (Pr < 12) E->SizePulse = Frange(0.05f, 0.14f);
            else if (Pr < 98) E->SizePulse = Frange(0.00f, 0.015f);
            else              E->SizePulse = Frange(0.00f, 0.45f);

            E->SizePulseT = Frange(0.f, 6.28f);
            E->Color        = 1 + (Xr() % NColors);

            RollPattern(E);

            E->PatternT = 0.f;

            // ---- wobble: ~72% of patterns wobble, mostly gently ----
            if (Frand() < 0.72f) {
                E->WobbleOn = 1;
                // strong cubic bias toward small; extremes rare
                E->AnimA1 = (0.3f + Fsmall() * 3.2f) * GOptWobble;
                E->AnimA2 = (0.3f + Fsmall() * 3.2f) * GOptWobble;
                E->AnimF1 = 0.4f + Frand() * 2.0f;
                E->AnimF2 = 0.4f + Frand() * 2.0f;
                E->AnimF1Vel = Frange(-0.3f, 0.3f);
                E->AnimF2Vel = Frange(-0.3f, 0.3f);
            } else {
                E->WobbleOn = 0;
                E->AnimA1 = E->AnimA2 = 0.0f;
                E->AnimF1 = 0.4f + Frand() * 1.0f;
                E->AnimF2 = 0.4f + Frand() * 1.0f;
                E->AnimF1Vel = 0.0f;
                E->AnimF2Vel = 0.0f;
            }

            // ---- wander: ~65% of patterns wander, mostly gently ----
            if (Frand() < 0.65f) {
                E->WanderOn = 1;
                float Ar = Fsmall();
                E->Accel     = (6.f + Ar * 30.f) * GOptWander;
                E->MaxSpeed = (10.f + Ar * 55.f) * GOptWander;
            } else {
                E->WanderOn = 0;
                E->Accel     = 0.f;
                E->MaxSpeed = 0.f;
            }

            E->InDur   = Frange(1.5f, 15.0f) * GOptFadeMul;
            E->HoldDur = Frange(8.0f, 45.0f);
            E->OutDur  = Frange(1.5f, 8.0f) * GOptFadeMul;
            E->Phase    = 0;
            E->Life     = 0.f;
            E->Presence = 0.f;
            E->Key      = PickNote();

            float SzU = (E->SizeBase - BufH * 0.02f) / (BufH * 0.58f);
            if (SzU < 0.f) SzU = 0.f;
            if (SzU > 1.f) SzU = 1.f;
            E->Velocity = 0.15f + SzU * 0.45f;

            // v4-style blend distribution (mostly small, some fuller)
            float b = Frand();
            if (Frand() < 0.55f) b *= 0.3f;
            E->Blend = b * 0.85f * GOptBlend;

            E->RetrigTimer = Frange(2.5f, 5.5f) / GOptNoteSpeedMul;
            E->Thickness    = Rrange(0, 2);
            E->WillMorph   = (Xr() % 100) < 30;
            E->NotePlaying = 0;
            return;
        }
    }
}

static void UpdateEntities(float Dt) {
    for (int I = 0; I < MaxEnt; I++) {
        Entity *E = &Ents[I];
        if (E->Phase == -1) continue;

        E->Life += Dt;
        E->PatternT += Dt;

        for (int K = 0; K < 32; K++) {
            if (E->PVel[K] == 0.0f) continue;
            E->P[K] += E->PVel[K] * Dt;
            float b   = E->PBase[K];
            float Mag = 0.15f * fabsf(b) + 0.02f;
            if (E->P[K] > b + Mag) { E->P[K] = b + Mag; E->PVel[K] = -E->PVel[K]; }
            if (E->P[K] < b - Mag) { E->P[K] = b - Mag; E->PVel[K] = -E->PVel[K]; }
        }
        E->AnimF1 += E->AnimF1Vel * Dt;
        if (E->AnimF1 < 0.25f) { E->AnimF1 = 0.25f; E->AnimF1Vel = -E->AnimF1Vel; }
        if (E->AnimF1 > 3.0f)  { E->AnimF1 = 3.0f;  E->AnimF1Vel = -E->AnimF1Vel; }
        E->AnimF2 += E->AnimF2Vel * Dt;
        if (E->AnimF2 < 0.25f) { E->AnimF2 = 0.25f; E->AnimF2Vel = -E->AnimF2Vel; }
        if (E->AnimF2 > 3.0f)  { E->AnimF2 = 3.0f;  E->AnimF2Vel = -E->AnimF2Vel; }

        if (E->Type == PWorm) {
            float Segstep = E->P[0] * BufH;
            float WormSpeed = 55.0f;
            E->HeadingVel += Frange(-E->P[1], E->P[1]) * Dt;
            if (E->HeadingVel >  E->P[2]) E->HeadingVel =  E->P[2];
            if (E->HeadingVel < -E->P[2]) E->HeadingVel = -E->P[2];
            E->Heading += E->HeadingVel * Dt;
            E->BodyX[0] += cosf(E->Heading) * WormSpeed * Dt;
            E->BodyY[0] += sinf(E->Heading) * WormSpeed * Dt;
            if (E->BodyX[0] < 10.f)          { E->BodyX[0] = 10.f;          E->Heading = 3.14159265f - E->Heading; }
            if (E->BodyX[0] > BufW - 10.f)  { E->BodyX[0] = BufW - 10.f;  E->Heading = 3.14159265f - E->Heading; }
            if (E->BodyY[0] < 10.f)          { E->BodyY[0] = 10.f;          E->Heading = -E->Heading; }
            if (E->BodyY[0] > BufH - 10.f)  { E->BodyY[0] = BufH - 10.f;  E->Heading = -E->Heading; }
            for (int K = 1; K < E->BodyLen; K++) {
                float Dx = E->BodyX[K-1] - E->BodyX[K];
                float Dy = E->BodyY[K-1] - E->BodyY[K];
                float D  = sqrtf(Dx*Dx + Dy*Dy);
                if (D > Segstep && D > 0.001f) {
                    float F = Segstep / D;
                    E->BodyX[K] = E->BodyX[K-1] - Dx * F;
                    E->BodyY[K] = E->BodyY[K-1] - Dy * F;
                }
            }
            E->X = E->BodyX[0];
            E->Y = E->BodyY[0];
            E->Vx = cosf(E->Heading) * WormSpeed;
            E->Vy = sinf(E->Heading) * WormSpeed;
            E->Angle = E->Heading;
        } else {
            if (E->WanderOn) {
                E->Vx += Frange(-E->Accel, E->Accel) * Dt;
                E->Vy += Frange(-E->Accel, E->Accel) * Dt;
                float Sp2 = E->Vx*E->Vx + E->Vy*E->Vy;
                float Mx2 = E->MaxSpeed * E->MaxSpeed;
                if (Sp2 > Mx2 && Sp2 > 0.001f) {
                    float F = E->MaxSpeed / sqrtf(Sp2);
                    E->Vx *= F; E->Vy *= F;
                }
            }
            E->X += E->Vx * Dt;
            E->Y += E->Vy * Dt;
            if (E->X <  20.f)         { E->X = 20.f;         E->Vx = -E->Vx; }
            if (E->X > BufW - 20.f)  { E->X = BufW - 20.f; E->Vx = -E->Vx; }
            if (E->Y <  20.f)         { E->Y = 20.f;         E->Vy = -E->Vy; }
            if (E->Y > BufH - 20.f)  { E->Y = BufH - 20.f; E->Vy = -E->Vy; }

            if (E->WanderOn) {
                E->Spin += Frange(-0.35f, 0.35f) * Dt;
                if (E->Spin >  2.0f) E->Spin =  2.0f;
                if (E->Spin < -2.0f) E->Spin = -2.0f;
            }
            E->Angle += E->Spin * Dt;
        }

        E->SizePulseT += Dt;
        E->Size = E->SizeBase * (1.0f + E->SizePulse * sinf(E->SizePulseT * 0.7f));

        if (E->Phase == 0) {
            float U = E->Life / E->InDur;
            if (U >= 1.0f) { E->Phase = 1; E->Life = 0.0f; E->Presence = 1.0f; }
            else E->Presence = U;

            if (Synth && !E->NotePlaying && E->Presence > 0.15f) {
                E->Key = PickNote();
                tsf_channel_set_presetindex(Synth, I, ColorPreset[E->Color - 1]);
                tsf_channel_note_on(Synth, I, E->Key, E->Velocity);
                E->NotePlaying = 1;
            }
        } else if (E->Phase == 1) {
            E->Presence = 1.0f;
            if (Synth && !E->NotePlaying) {
                E->Key = PickNote();
                tsf_channel_set_presetindex(Synth, I, ColorPreset[E->Color - 1]);
                tsf_channel_note_on(Synth, I, E->Key, E->Velocity);
                E->NotePlaying = 1;
            }
            E->RetrigTimer -= Dt;
            if (E->RetrigTimer <= 0.0f && Synth) {
                tsf_channel_note_off(Synth, I, E->Key);
                float SizeRatio = E->Size / E->SizeBase;
                int Bias = 0;
                if (SizeRatio > 1.05f && (Xr() % 100) < 70) Bias =  1;
                else if (SizeRatio < 0.95f && (Xr() % 100) < 70) Bias = -1;
                // If size didn't already set a pitch direction, sometimes let
                // the entity's current vertical travel direction nudge it
                // instead: moving up biases the next note higher, down lower.
                if (GOptAudioreact > 0.0f && Bias == 0 && (Xr() % 100) < (int)(35 * GOptAudioreact)) {
                    float VyNorm = -E->Vy / 45.0f;
                    if (VyNorm > 0.5f) Bias = 2;
                    else if (VyNorm < -0.5f) Bias = -2;
                }
                E->Key = PickNoteBiased(Bias);
                float PulseAct = E->SizePulse * fabsf(sinf(E->SizePulseT * 0.7f));
                float Speed = sqrtf(E->Vx*E->Vx + E->Vy*E->Vy);
                float SpeedAct = Speed / 40.0f;
                float Activity = PulseAct + SpeedAct * 0.6f;
                if (Activity > 1.5f) Activity = 1.5f;
                // Random velocity jitter, plus a small lift from how strongly
                // the shape is currently pulsing, so a pulsing shape's next
                // note lands a bit louder. Set once here at the note change;
                // untouched until the following retrigger.
                float VelMul = Frange(0.85f, 1.15f) + PulseAct * 0.16f * GOptAudioreact;
                tsf_channel_note_on(Synth, I, E->Key, E->Velocity * VelMul);
                float BaseInt = Frange(1.8f, 4.0f);
                E->RetrigTimer = BaseInt / (1.0f + 1.8f * Activity) / GOptNoteSpeedMul;
                if (E->RetrigTimer < 0.5f) E->RetrigTimer = 0.5f;
            }
            if (E->Life >= E->HoldDur) { E->Phase = 2; E->Life = 0.0f; }
        } else if (E->Phase == 2) {
            float U = E->Life / E->OutDur;
            if (U >= 1.0f) {
                if (Synth && E->NotePlaying) {
                    tsf_channel_note_off(Synth, I, E->Key);
                    E->NotePlaying = 0;
                }
                if (E->WillMorph) {
                    int   Keep = E->Color;
                    float Kv   = E->Velocity;
                    RollPattern(E);
                    E->Color       = Keep;
                    E->Velocity    = Kv;
                    E->Phase       = 0;
                    E->Life        = 0.0f;
                    E->Presence    = 0.0f;
                    E->PatternT   = 0.0f;
                    if (Frand() < 0.72f) {
                        E->WobbleOn = 1;
                        E->AnimA1 = (0.3f + Fsmall() * 3.2f) * GOptWobble;
                        E->AnimA2 = (0.3f + Fsmall() * 3.2f) * GOptWobble;
                        E->AnimF1 = 0.4f + Frand() * 2.0f;
                        E->AnimF2 = 0.4f + Frand() * 2.0f;
                        E->AnimF1Vel = Frange(-0.3f, 0.3f);
                        E->AnimF2Vel = Frange(-0.3f, 0.3f);
                    } else {
                        E->WobbleOn = 0;
                        E->AnimA1 = E->AnimA2 = 0.0f;
                        E->AnimF1Vel = E->AnimF2Vel = 0.0f;
                    }
                    if (Frand() < 0.65f) {
                        E->WanderOn = 1;
                        float Ar = Fsmall();
                        E->Accel     = (6.f + Ar * 30.f) * GOptWander;
                        E->MaxSpeed = (10.f + Ar * 55.f) * GOptWander;
                    } else {
                        E->WanderOn = 0;
                        E->Accel     = 0.f;
                        E->MaxSpeed = 0.f;
                    }
                    E->InDur   = Frange(1.5f, 15.0f) * GOptFadeMul;
                    E->HoldDur = Frange(8.0f, 45.0f);
                    E->OutDur  = Frange(1.5f, 8.0f) * GOptFadeMul;
                    E->Thickness   = Rrange(0, 2);
                    E->RetrigTimer = Frange(2.5f, 5.5f) / GOptNoteSpeedMul;
                    E->WillMorph  = (Xr() % 100) < 30;
                    float b = Frand();
                    if (Frand() < 0.55f) b *= 0.3f;
                    E->Blend = b * 0.85f * GOptBlend;
                } else {
                    E->Phase = -1;
                }
            } else {
                E->Presence = 1.0f - U;
                if (Synth && E->NotePlaying && E->Presence < 0.3f) {
                    tsf_channel_note_off(Synth, I, E->Key);
                    E->NotePlaying = 0;
                }
            }
        }
    }
}

// Debug option: entities collide and bounce off each other, treated as
// circles sized by E->Size. Worm entities steer via Heading instead of
// Vx/Vy, since UpdateEntities recomputes their Vx/Vy from Heading every
// frame anyway. On impact, both entities' RetrigTimer is pulled down so the
// next note-change (and whatever it picks up from the post-collision speed)
// lands almost immediately, making the bounce audible right away.
static void UpdatePhysics(void) {
    if (!GOptPhysics) return;
    for (int I = 0; I < MaxEnt; I++) {
        Entity *A = &Ents[I];
        if (A->Phase == -1) continue;
        for (int J = I + 1; J < MaxEnt; J++) {
            Entity *B = &Ents[J];
            if (B->Phase == -1) continue;

            float Dx = B->X - A->X, Dy = B->Y - A->Y;
            float Dist2 = Dx*Dx + Dy*Dy;
            float Ra = A->Size * 0.5f, Rb = B->Size * 0.5f;
            float MinDist = Ra + Rb;
            if (Dist2 >= MinDist * MinDist || Dist2 < 0.0001f) continue;

            float Dist = sqrtf(Dist2);
            float Nx = Dx / Dist, Ny = Dy / Dist;

            float Overlap = (MinDist - Dist) * 0.5f;
            A->X -= Nx * Overlap; A->Y -= Ny * Overlap;
            B->X += Nx * Overlap; B->Y += Ny * Overlap;

            float Rvx = B->Vx - A->Vx, Rvy = B->Vy - A->Vy;
            float VelAlongNormal = Rvx * Nx + Rvy * Ny;
            if (VelAlongNormal > 0.0f) continue; // already moving apart

            float Restitution = 0.9f;
            float Jimp = -(1.0f + Restitution) * VelAlongNormal * 0.5f;
            float Ix = Jimp * Nx, Iy = Jimp * Ny;

            if (A->Type == PWorm) { A->Heading = atan2f(-Ny, -Nx) + Frange(-0.3f, 0.3f); A->HeadingVel = 0.0f; }
            else { A->Vx -= Ix; A->Vy -= Iy; }
            if (B->Type == PWorm) { B->Heading = atan2f(Ny, Nx) + Frange(-0.3f, 0.3f); B->HeadingVel = 0.0f; }
            else { B->Vx += Ix; B->Vy += Iy; }

            if (A->Phase == 1 && A->RetrigTimer > 0.05f) A->RetrigTimer = 0.05f;
            if (B->Phase == 1 && B->RetrigTimer > 0.05f) B->RetrigTimer = 0.05f;
        }
    }
}

// Debug option: pushes pitch-bend and volume to every playing channel every
// frame, following the entity's current motion/pulse continuously, instead
// of only at the next note change. Off by default — normal play never calls
// this, and sounds exactly as without it.
static void UpdateLiveAudio(void) {
    if (!Synth || !GOptLiveAudio) return;
    for (int I = 0; I < MaxEnt; I++) {
        Entity *E = &Ents[I];
        if (E->Phase == -1 || !E->NotePlaying) continue;

        float VyNorm = -E->Vy / 45.0f;
        if (VyNorm >  1.0f) VyNorm =  1.0f;
        if (VyNorm < -1.0f) VyNorm = -1.0f;
        float Semis = VyNorm * 1.6f * GOptAudioreact;
        if (Semis >  2.0f) Semis =  2.0f;
        if (Semis < -2.0f) Semis = -2.0f;
        int Pw = 8192 + (int)((Semis / 2.0f) * 8191.0f);
        if (Pw < 0) Pw = 0;
        if (Pw > 16383) Pw = 16383;
        tsf_channel_set_pitchrange(Synth, I, 2.0f);
        tsf_channel_set_pitchwheel(Synth, I, Pw);

        float Pulse = E->SizePulse * sinf(E->SizePulseT * 0.7f);
        float Vol = 1.0f + Pulse * 0.6f * GOptAudioreact;
        if (Vol < 0.15f) Vol = 0.15f;
        if (Vol > 1.6f)  Vol = 1.6f;
        tsf_channel_set_volume(Synth, I, Vol * E->Presence);
    }
}

static void RenderEntities(void) {
    for (int I = 0; I < MaxEnt; I++) {
        if (Ents[I].Phase == -1) continue;
        RenderEntity(&Ents[I]);
    }
}

// ------------------------- background noise -------------------------
static void UpdateBg(void) {
    int n = BufW * BufH;
    if (!GOptNoise) {
        memset(Bg, 0, (size_t)n);
        memset(BgTint, 0, (size_t)n);
        return;
    }
    for (int I = 0; I < n; I++) {
        uint32_t r = Xr();
        uint8_t  V = (uint8_t)(r & 0x1Fu);
        if ((r & 0xFFu) < 22u) V = (uint8_t)(V + 28);
        Bg[I] = V;
        BgTint[I] = ((r >> 8) & 0x3FFu) < 4u ? 1u : 0u;
    }
}

static void Composite(void) {
    int n = BufW * BufH;
    for (int I = 0; I < n; I++) {
        uint8_t G = Bg[I];
        uint8_t r = G, Gg = G, b = G;
        if (BgTint[I]) {
            int Rr = G + 18;
            r = (Rr > 255) ? 255 : (uint8_t)Rr;
        }
        uint8_t Fi = FgInt[I];
        if (Fi) {
            int Ci = (int)FgCol[I] - 1;
            if ((unsigned)Ci < (unsigned)NColors) {
                uint8_t Cr=Colors[Ci][0], Cg=Colors[Ci][1], Cb=Colors[Ci][2];
                r  = (uint8_t)((r  * (255 - Fi) + Cr * Fi) / 255);
                Gg = (uint8_t)((Gg * (255 - Fi) + Cg * Fi) / 255);
                b  = (uint8_t)((b  * (255 - Fi) + Cb * Fi) / 255);
            }
            FgInt[I] = Fi > 4 ? (uint8_t)(Fi - 4) : 0;
        }
        Pixbuf[I] = 0xFF000000u | ((uint32_t)r << 16)
                                | ((uint32_t)Gg << 8) | (uint32_t)b;
    }
}

// ------------------------- debug HUD -------------------------
// Tiny 3x5 bitmap font, just enough characters for the HUD line below.
// Each glyph is 5 rows of 3 bits (bit 2 = leftmost column).
static const char *HudFontChars = "0123456789:/XFPTVCRS ";
static const uint8_t HudFontRows[][5] = {
    {0b111,0b101,0b101,0b101,0b111}, // 0
    {0b010,0b110,0b010,0b010,0b111}, // 1
    {0b111,0b001,0b111,0b100,0b111}, // 2
    {0b111,0b001,0b111,0b001,0b111}, // 3
    {0b101,0b101,0b111,0b001,0b001}, // 4
    {0b111,0b100,0b111,0b001,0b111}, // 5
    {0b111,0b100,0b111,0b101,0b111}, // 6
    {0b111,0b001,0b001,0b001,0b001}, // 7
    {0b111,0b101,0b111,0b101,0b111}, // 8
    {0b111,0b101,0b111,0b001,0b111}, // 9
    {0b000,0b010,0b000,0b010,0b000}, // :
    {0b001,0b001,0b010,0b100,0b100}, // /
    {0b101,0b101,0b010,0b101,0b101}, // X
    {0b111,0b100,0b111,0b100,0b100}, // F
    {0b111,0b101,0b111,0b100,0b100}, // P
    {0b111,0b010,0b010,0b010,0b010}, // T
    {0b101,0b101,0b101,0b101,0b010}, // V
    {0b111,0b100,0b100,0b100,0b111}, // C
    {0b111,0b101,0b111,0b110,0b101}, // R
    {0b111,0b100,0b111,0b001,0b111}, // S
    {0b000,0b000,0b000,0b000,0b000}, // space
};

static void HudPlot(int X, int Y, uint32_t Color) {
    if (X < 0 || Y < 0 || X >= BufW || Y >= BufH) return;
    Pixbuf[Y * BufW + X] = Color;
}

static void HudChar(int X, int Y, char C, int Scale, uint32_t Color) {
    const char *P = strchr(HudFontChars, C);
    if (!P) return;
    int Idx = (int)(P - HudFontChars);
    for (int Row = 0; Row < 5; Row++) {
        uint8_t Bits = HudFontRows[Idx][Row];
        for (int Col = 0; Col < 3; Col++) {
            if (!(Bits & (1 << (2 - Col)))) continue;
            for (int Sy = 0; Sy < Scale; Sy++)
                for (int Sx = 0; Sx < Scale; Sx++)
                    HudPlot(X + Col * Scale + Sx, Y + Row * Scale + Sy, Color);
        }
    }
}

static void HudText(int X, int Y, const char *Str, int Scale, uint32_t Color) {
    int Cx = X;
    for (; *Str; Str++) {
        HudChar(Cx, Y, *Str, Scale, Color);
        Cx += (3 + 1) * Scale;
    }
}

static void DrawHud(float Dt) {
    static float SmoothFps = 60.0f;
    float Fps = Dt > 0.0001f ? (1.0f / Dt) : SmoothFps;
    SmoothFps = SmoothFps * 0.9f + Fps * 0.1f;

    int PatCount = 0, VoiceCount = 0;
    for (int I = 0; I < MaxEnt; I++) {
        if (Ents[I].Phase == -1) continue;
        PatCount++;
        if (Ents[I].NotePlaying) VoiceCount++;
    }

    char Line[96];
    snprintf(Line, sizeof(Line), "FPS:%d PT:%d VC:%d/%d RS:%dX%d",
             (int)(SmoothFps + 0.5f), PatCount, VoiceCount, MaxEnt, BufW, BufH);

    int Scale = BufH >= 540 ? 2 : 1;
    int BarH = (5 * Scale) + (4 * Scale);
    if (BarH > BufH) BarH = BufH;
    for (int Y = 0; Y < BarH; Y++)
        for (int X = 0; X < BufW; X++) {
            uint32_t P = Pixbuf[Y * BufW + X];
            uint32_t R = ((P >> 16) & 0xFF) * 2 / 5;
            uint32_t G = ((P >> 8)  & 0xFF) * 2 / 5;
            uint32_t B = ( P        & 0xFF) * 2 / 5;
            Pixbuf[Y * BufW + X] = 0xFF000000u | (R << 16) | (G << 8) | B;
        }
    HudText(Scale * 2, Scale * 2, Line, Scale, 0xFF30FF60u);
}

// ------------------------- palette & SF2 -------------------------
static void GenColors(void) {
    if (GOptColors > 0) NColors = GOptColors;
    else                  NColors = Rrange(2, 256);

    int NWhite=0, NBlack=0, NGray=0;
    if (NColors >= 4) {
        if (Xr() % 100 < 30) NWhite = 1;
        if (Xr() % 100 < 20) NBlack = 1;
        if (Xr() % 100 < 10) NGray  = 1;
    } else {
        if (Xr() % 100 < 15) NWhite = 1;
    }
    int Achroma = NWhite + NBlack + NGray;
    int ChromaticN = NColors - Achroma;
    if (ChromaticN < 1) ChromaticN = 1;

    for (int I = 0; I < ChromaticN; I++) {
        float H = Frand() * 360.0f;
        float S = 0.85f + Frand() * 0.15f;
        float V = 0.90f + Frand() * 0.10f;
        float C = V * S;
        float Hh = H / 60.0f;
        float X = C * (1.0f - fabsf(fmodf(Hh, 2.0f) - 1.0f));
        float Rr=0,Gg=0,Bb=0;
        if      (Hh<1){Rr=C;Gg=X;} else if(Hh<2){Rr=X;Gg=C;}
        else if (Hh<3){Gg=C;Bb=X;} else if(Hh<4){Gg=X;Bb=C;}
        else if (Hh<5){Rr=X;Bb=C;} else {Rr=C;Bb=X;}
        float M = V - C;
        Colors[I][0]=(uint8_t)((Rr+M)*255.f);
        Colors[I][1]=(uint8_t)((Gg+M)*255.f);
        Colors[I][2]=(uint8_t)((Bb+M)*255.f);
    }
    int Idx = ChromaticN;
    if (NWhite){Colors[Idx][0]=Colors[Idx][1]=Colors[Idx][2]=255; Idx++;}
    if (NBlack){Colors[Idx][0]=Colors[Idx][1]=Colors[Idx][2]=0;   Idx++;}
    if (NGray) {Colors[Idx][0]=Colors[Idx][1]=Colors[Idx][2]=128; Idx++;}
}

static char Sf2Path[1024];
static char ExeDir[512];

// Directory of the running executable (not the current working directory).
static void GetExeDir(void) {
    ssize_t n = readlink("/proc/self/exe", ExeDir, sizeof(ExeDir) - 1);
    if (n > 0) {
        ExeDir[n] = 0;
        char *Slash = strrchr(ExeDir, '/');
        if (Slash) {
            if (Slash == ExeDir) Slash[1] = 0;   // binary directly in "/"
            else                  *Slash = 0;
            return;
        }
    }
    // Fallback: SDL's own idea of the base path
    char *Base = SDL_GetBasePath();
    if (Base) {
        snprintf(ExeDir, sizeof(ExeDir), "%s", Base);
        size_t l = strlen(ExeDir);
        if (l > 1 && ExeDir[l - 1] == '/') ExeDir[l - 1] = 0;
        SDL_free(Base);
        return;
    }
    snprintf(ExeDir, sizeof(ExeDir), ".");
}

static int FindSf2(void) {
    GetExeDir();
    DIR *D = opendir(ExeDir);
    if (!D) return 0;
    char Cand[64][256]; int n=0;
    struct dirent *De;
    while ((De = readdir(D)) && n < 64) {
        int l = (int)strlen(De->d_name);
        if (l > 4 && strcasecmp(De->d_name + l - 4, ".sf2") == 0) {
            strncpy(Cand[n], De->d_name, 255);
            Cand[n][255] = 0; n++;
        }
    }
    closedir(D);
    if (!n) return 0;
    int Pick = (int)(Xr() % (uint32_t)n);
    snprintf(Sf2Path, sizeof(Sf2Path), "%.511s/%.255s", ExeDir, Cand[Pick]);
    return 1;
}
// Loads Icon.png from next to the executable and sets it as the window's
// icon (titlebar/taskbar/alt-tab). Purely cosmetic — any failure here (file
// missing, bad PNG, old SDL without SurfaceWithFormatFrom) is silently
// skipped rather than stopping the program.
static void SetWindowIconFromExeDir(SDL_Window *Win) {
    GetExeDir();
    char IconPath[1040];
    snprintf(IconPath, sizeof(IconPath), "%.511s/Icon.png", ExeDir);

    int Iw = 0, Ih = 0, Ich = 0;
    unsigned char *Pixels = stbi_load(IconPath, &Iw, &Ih, &Ich, 4);
    if (!Pixels) return;

    SDL_Surface *Surf = SDL_CreateRGBSurfaceWithFormatFrom(
        Pixels, Iw, Ih, 32, Iw * 4, SDL_PIXELFORMAT_RGBA32);
    if (Surf) {
        SDL_SetWindowIcon(Win, Surf);
        SDL_FreeSurface(Surf);
    }
    stbi_image_free(Pixels);
}

static void AssignPresets(void) {
    if (!Synth) return;
    int Pc = tsf_get_presetcount(Synth);
    if (Pc <= 0) return;
    for (int I = 0; I < NColors; I++)
        ColorPreset[I] = (int)(Xr() % (uint32_t)Pc);
}

// ------------------------- audio -------------------------
static void AudioCb(void *Ud, Uint8 *Stream, int Len) {
    (void)Ud;
    if (GOptMute) { memset(Stream, 0, Len); return; }
    short *Out = (short *)Stream;
    int Frames = Len / 4;
    if (Synth) {
        tsf_render_short(Synth, Out, Frames, 0);
        int Total = Frames * 2;
        for (int I = 0; I < Total; I++) {
            int V = (int)Out[I] * 40 / 100;
            if (V >  32767) V =  32767;
            if (V < -32768) V = -32768;
            Out[I] = (short)V;
        }
    } else {
        memset(Stream, 0, Len);
    }
}

// ------------------------- resolution -------------------------
// Derives the logical noise-buffer size from the real renderer output size
// (SDL_GetRendererOutputSize, which accounts for HighDPI). By default this is
// native: one logical pixel equals one real screen pixel, continuously
// matching the window's current size. The "Pixel size" menu option can force
// a bigger cell instead, where several real screen pixels share one logical
// noise-pixel, for a chunkier look or to reduce the per-pixel noise workload
// on very large windows.
static int ResolveCell(int Pw, int Ph) {
    (void)Pw; (void)Ph;
    if (GOptPixelsize > 0) return GOptPixelsize;
    return 1;
}
static void ComputeBufSize(SDL_Renderer *Ren, int *OutW, int *OutH) {
    int Pw = 0, Ph = 0;
    SDL_GetRendererOutputSize(Ren, &Pw, &Ph);
    if (Pw <= 0 || Ph <= 0) { Pw = 960; Ph = 540; }
    int Cell = ResolveCell(Pw, Ph);
    int Nw = Pw / Cell, Nh = Ph / Cell;
    if (Nw < 160) Nw = 160;
    if (Nh < 90)  Nh = 90;
    *OutW = Nw; *OutH = Nh;
}

// Proportionally remaps everything measured in buffer-pixel units when the
// window (and therefore BUF_W/BUF_H) changes size, so every shape keeps the
// same relative position and relative size on screen.
static void RescaleEntities(float Sx, float Sy) {
    float S = 0.5f * (Sx + Sy);
    for (int I = 0; I < MaxEnt; I++) {
        Entity *E = &Ents[I];
        if (E->Phase == -1) continue;
        E->X *= Sx;  E->Y *= Sy;
        E->Vx *= Sx; E->Vy *= Sy;
        E->Size *= S; E->SizeBase *= S;
        E->MaxSpeed *= S; E->Accel *= S;
        for (int K = 0; K < E->BodyLen; K++) {
            E->BodyX[K] *= Sx;
            E->BodyY[K] *= Sy;
        }
    }
}

// ------------------------- buffers -------------------------
static void AllocBuffers(void) {
    int n = BufW * BufH;
    Pixbuf  = malloc(sizeof(uint32_t) * n);
    Bg      = malloc(n);
    BgTint = malloc(n);
    FgInt  = malloc(n);
    FgCol  = malloc(sizeof(uint16_t) * n);
    memset(FgInt, 0, n);
    memset(FgCol, 0, sizeof(uint16_t) * n);
}
static void FreeBuffers(void) {
    free(Pixbuf); free(Bg); free(BgTint); free(FgInt); free(FgCol);
}

// ------------------------- phase machine -------------------------
static int   GPhase = 0;
static float GPhaseTimer = 0.0f;
static float GSilentTarget = 0.0f;
static int   GSpawnChecks = 0;

// ------------------------- menu -------------------------
static void OptionsMenu(void) {
    char Buf[128];
    printf("\n");
    printf("==========================================\n");
    printf("  Noise — launch options\n");
    printf("==========================================\n");
    printf("  (press Enter on any line to accept default)\n\n");

    printf("  Number of colors [2-256, blank = random]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V >= 2 && V <= 256) GOptColors = V;
    }

    printf("  Enable quiet/silent phases? [Y/n]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        if (Buf[0] == 'n' || Buf[0] == 'N') GOptSilent = 0;
    }

    printf("  Wobble multiplier  [0.0-3.0, 1.0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.0f && V <= 3.0f) GOptWobble = V;
    }

    printf("  Wander multiplier  [0.0-6.0, 1.0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.0f && V <= 6.0f) GOptWander = V;
    }

    printf("  Edge-blend / dithering multiplier [0.0-3.0, 1.65]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.0f && V <= 3.0f) GOptBlend = V;
    }

    printf("  Pixel size [0=auto/native, 1=force native, 2-6=chunkier retro pixels, blank=auto]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V >= 0 && V <= 6) GOptPixelsize = V;
    }

    printf("  Audio-reactivity strength [0.0-2.0, 1.0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.0f && V <= 2.0f) GOptAudioreact = V;
    }

    printf("  Zoom [1.0-4.0, 1.0 = off]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 1.0f && V <= 4.0f) GOptZoom = V;
    }

    printf("  Appear/disappear duration multiplier [0.2-4.0, 1.0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.2f && V <= 4.0f) GOptFadeMul = V;
    }

    printf("  Note-change speed multiplier [0.2-5.0, 1.0 = normal, 5.0 = disco]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.2f && V <= 5.0f) GOptNoteSpeedMul = V;
    }

    printf("\n  -- Debug (off by default, can change a lot) --\n");

    printf("  Physics: entities collide/bounce [0/1, 0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V == 0 || V == 1) GOptPhysics = V;
    }

    printf("  Live audio: continuous pitch/volume instead of per-note [0/1, 0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V == 0 || V == 1) GOptLiveAudio = V;
    }

    printf("  Background noise [0/1, 1]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V == 0 || V == 1) GOptNoise = V;
    }

    printf("  Motion speed multiplier (drift/spin/worm/wobble only) [0.1-5.0, 1.0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        float V = atof(Buf);
        if (V >= 0.1f && V <= 5.0f) GOptMotionSpeed = V;
    }

    printf("  HUD: FPS / pattern / voice / resolution bar [0/1, 0]: ");
    fflush(stdout);
    if (fgets(Buf, sizeof(Buf), stdin)) {
        int V = atoi(Buf);
        if (V == 0 || V == 1) GOptHud = V;
    }

    printf("\n  Starting...\n\n");
}

// ------------------------- main -------------------------
int main(int Argc, char **Argv) {
    SDL_SetMainReady();

    for (int I = 1; I < Argc; I++) {
        if (strcmp(Argv[I], "--menu") == 0 ||
            strcmp(Argv[I], "-m") == 0) {
            OptionsMenu();
        } else if (strcmp(Argv[I], "--width") == 0 && I + 1 < Argc) {
            GOptWinW = atoi(Argv[++I]);
        } else if (strcmp(Argv[I], "--height") == 0 && I + 1 < Argc) {
            GOptWinH = atoi(Argv[++I]);
        } else if (strcmp(Argv[I], "--silent") == 0 ||
                   strcmp(Argv[I], "-s") == 0) {
            GOptMute = 1;
        }
    }
    if (GOptWinW <= 0) GOptWinW = 960;
    if (GOptWinH <= 0) GOptWinH = 540;

    RngState = (uint32_t)time(NULL)
              ^ (uint32_t)clock()
              ^ (uint32_t)getpid() * 2654435761u;
    if (!RngState) RngState = 0xDEADBEEFu;
    for (int I = 0; I < 32; I++) Xr();

    PickScale();

    int HaveSf2 = FindSf2();
    if (HaveSf2) {
        Synth = tsf_load_filename(Sf2Path);
        if (Synth) {
            tsf_set_output(Synth, TSF_STEREO_INTERLEAVED, 44100, 0.0f);
            tsf_set_max_voices(Synth, 64);
            fprintf(stderr, "noise: loaded %s (%d presets)\n",
                    Sf2Path, tsf_get_presetcount(Synth));
        }
    }
    if (!Synth) fprintf(stderr, "noise: no .sf2 found — running silent\n");

    GenColors();
    AssignPresets();

    // Sets the window's app_id (Wayland) / WM_CLASS (X11) explicitly, so
    // window-list taskbars/docks that match windows against a .desktop
    // file's Name or StartupWMClass get a stable, predictable string
    // instead of whatever SDL would otherwise derive from the binary name.
    // SDL2's Wayland driver reads this from an environment variable, not
    // from SDL_HINT_APP_NAME (that hint controls unrelated things, like the
    // PulseAudio stream name) — both must be set before SDL_Init.
    setenv("SDL_VIDEO_WAYLAND_WMCLASS", "TrafkVerseScreensaver", 1);
    setenv("SDL_VIDEO_X11_WMCLASS", "TrafkVerseScreensaver", 1);
    SDL_SetHint(SDL_HINT_APP_NAME, "TrafkVerseScreensaver");

    if (SDL_Init(SDL_INIT_VIDEO | SDL_INIT_AUDIO) != 0) {
        fprintf(stderr, "SDL_Init: %s\n", SDL_GetError());
        return 1;
    }

    SDL_Window *Win = SDL_CreateWindow(
        "TrafkVerseScreensaver",
        SDL_WINDOWPOS_CENTERED, SDL_WINDOWPOS_CENTERED,
        GOptWinW, GOptWinH,
        SDL_WINDOW_RESIZABLE | SDL_WINDOW_SHOWN | SDL_WINDOW_ALLOW_HIGHDPI);
    if (!Win) { fprintf(stderr, "CreateWindow: %s\n", SDL_GetError()); return 1; }
    // WICHTIG (siehe Chat, hyprwm/Hyprland#16446): auf Hyprland 0.56.2
    // wird eine per window_rule gesetzte Groesse fuer floatende Fenster
    // unter dem neuen Lua-Parser komplett ignoriert - das Fenster
    // bekommt stattdessen Hyprlands eigene Default-Floating-Groesse
    // (beobachtet: ~35% der Monitorgroesse), unabhaengig davon, welche
    // Groesse SDL_CreateWindow oben angefordert hat. Der im Issue
    // bestaetigte Workaround ist, die angeforderte Groesse client-seitig
    // als VERBINDLICH (nicht nur als Vorschlag) zu markieren - das
    // geschieht hier durch Min=Max=angeforderte Groesse.
    SDL_SetWindowMinimumSize(Win, GOptWinW, GOptWinH);
    SDL_SetWindowMaximumSize(Win, GOptWinW, GOptWinH);
    SetWindowIconFromExeDir(Win);

    SDL_Renderer *Ren = SDL_CreateRenderer(
        Win, -1,
        SDL_RENDERER_ACCELERATED | SDL_RENDERER_PRESENTVSYNC);
    if (!Ren) Ren = SDL_CreateRenderer(Win, -1, SDL_RENDERER_SOFTWARE);
    if (!Ren) { fprintf(stderr, "CreateRenderer: %s\n", SDL_GetError()); return 1; }

    // BufW/BufH are derived from the real renderer output resolution;
    // see compute_buf_size() above.
    ComputeBufSize(Ren, &BufW, &BufH);
    SDL_RenderSetLogicalSize(Ren, BufW, BufH);
    SDL_SetHint(SDL_HINT_RENDER_SCALE_QUALITY, "nearest");

    SDL_Texture *Tex = SDL_CreateTexture(
        Ren, SDL_PIXELFORMAT_ARGB8888,
        SDL_TEXTUREACCESS_STREAMING, BufW, BufH);

    SDL_AudioSpec Want, Have; SDL_zero(Want);
    Want.freq=44100; Want.format=AUDIO_S16SYS; Want.channels=2;
    Want.samples=512; Want.callback=AudioCb;
    SDL_AudioDeviceID Adev = SDL_OpenAudioDevice(NULL, 0, &Want, &Have, 0);
    if (Adev) SDL_PauseAudioDevice(Adev, 0);

    AllocBuffers();
    for (int I = 0; I < MaxEnt; I++) Ents[I].Phase = -1;

    Uint32 Last = SDL_GetTicks();
    float  SpawnTimer = 0.2f;
    int    Running = 1;

    while (Running) {
        SDL_Event Ev;
        while (SDL_PollEvent(&Ev)) {
            if (Ev.type == SDL_QUIT) Running = 0;
            else if (Ev.type == SDL_KEYDOWN &&
                     Ev.key.keysym.sym == SDLK_ESCAPE) Running = 0;
            else if (Ev.type == SDL_WINDOWEVENT &&
                     Ev.window.event == SDL_WINDOWEVENT_SIZE_CHANGED) {
                int Nw, Nh;
                ComputeBufSize(Ren, &Nw, &Nh);
                if (Nw != BufW || Nh != BufH) {
                    float Sx = (float)Nw / (float)BufW;
                    float Sy = (float)Nh / (float)BufH;
                    RescaleEntities(Sx, Sy);
                    BufW = Nw; BufH = Nh;
                    FreeBuffers();
                    AllocBuffers();
                    SDL_DestroyTexture(Tex);
                    Tex = SDL_CreateTexture(Ren, SDL_PIXELFORMAT_ARGB8888,
                                            SDL_TEXTUREACCESS_STREAMING,
                                            BufW, BufH);
                    SDL_RenderSetLogicalSize(Ren, BufW, BufH);
                }
            }
        }

        Uint32 Now = SDL_GetTicks();
        float Dt = (Now - Last) * 0.001f;
        Last = Now;
        if (Dt > 0.1f) Dt = 0.1f;

        // Phase machine
        if (GPhase == 0) {
            SpawnTimer -= Dt;
            if (SpawnTimer <= 0.0f) {
                SpawnEntity();
                GSpawnChecks++;
                if (GOptSilent && GSpawnChecks >= 4) {
                    int r = (int)(Xr() % 1000);
                    if (r < 15) {
                        GPhase = 2;
                        GPhaseTimer = 0.0f;
                        GSilentTarget = Frange(3.0f, 7.0f);
                    } else if (r < 165) {
                        GPhase = 1;
                        GPhaseTimer = Frange(15.0f, 40.0f);
                    }
                    GSpawnChecks = 0;
                }
                SpawnTimer = Frange(3.0f, 8.0f);
            }
        } else if (GPhase == 1) {
            GPhaseTimer -= Dt;
            SpawnTimer -= Dt;
            if (SpawnTimer <= 0.0f) {
                SpawnEntity();
                SpawnTimer = Frange(9.0f, 18.0f);
            }
            if (GPhaseTimer <= 0.0f) {
                GPhase = 0;
                GSpawnChecks = 0;
                SpawnTimer = Frange(1.0f, 3.0f);
            }
        } else {
            int AnyAlive = 0;
            for (int I = 0; I < MaxEnt; I++)
                if (Ents[I].Phase != -1) { AnyAlive = 1; break; }
            if (!AnyAlive) {
                GPhaseTimer += Dt;
                if (GPhaseTimer >= GSilentTarget) {
                    GPhase = 0;
                    GPhaseTimer = 0.0f;
                    GSpawnChecks = 0;
                    SpawnTimer = Frange(0.5f, 2.0f);
                }
            }
        }

        // NOTE: fg_int is intentionally NOT cleared here — the composite's
        // "-4 per frame" decay produces the short-lived trail / motion-blur
        // effect when shapes move or rotate.

        UpdateEntities(Dt * GOptMotionSpeed);
        UpdatePhysics();
        UpdateLiveAudio();
        UpdateBg();
        RenderEntities();
        Composite();
        if (GOptHud) DrawHud(Dt);

        SDL_UpdateTexture(Tex, NULL, Pixbuf, BufW * 4);
        SDL_RenderClear(Ren);
        if (GOptZoom > 1.0f) {
            int Zw = (int)(BufW / GOptZoom);
            int Zh = (int)(BufH / GOptZoom);
            if (Zw < 8) Zw = 8;
            if (Zh < 8) Zh = 8;
            SDL_Rect Src = { (BufW - Zw) / 2, (BufH - Zh) / 2, Zw, Zh };
            SDL_RenderCopy(Ren, Tex, &Src, NULL);
        } else {
            SDL_RenderCopy(Ren, Tex, NULL, NULL);
        }
        SDL_RenderPresent(Ren);
    }

    if (Synth) tsf_close(Synth);
    if (Adev)  SDL_CloseAudioDevice(Adev);
    SDL_DestroyTexture(Tex);
    SDL_DestroyRenderer(Ren);
    SDL_DestroyWindow(Win);
    SDL_Quit();
    FreeBuffers();
    return 0;
}