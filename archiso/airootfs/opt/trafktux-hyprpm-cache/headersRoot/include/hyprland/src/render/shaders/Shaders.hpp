#pragma once
#include <map>
static const std::map<std::string, std::string> SHADERS = {
{"blur1.frag",
#include "./blur1.frag.inc"
},
{"blur1.glsl",
#include "./blur1.glsl.inc"
},
{"blur2.frag",
#include "./blur2.frag.inc"
},
{"blur2.glsl",
#include "./blur2.glsl.inc"
},
{"blurfinish.frag",
#include "./blurfinish.frag.inc"
},
{"blurFinish.glsl",
#include "./blurFinish.glsl.inc"
},
{"blurprepare.frag",
#include "./blurprepare.frag.inc"
},
{"blurprepare.glsl",
#include "./blurprepare.glsl.inc"
},
{"border.frag",
#include "./border.frag.inc"
},
{"border.glsl",
#include "./border.glsl.inc"
},
{"CM.glsl",
#include "./CM.glsl.inc"
},
{"cm_helpers.glsl",
#include "./cm_helpers.glsl.inc"
},
{"constants.h",
#include "./constants.h.inc"
},
{"defines.h",
#include "./defines.h.inc"
},
{"ext.frag",
#include "./ext.frag.inc"
},
{"gain.glsl",
#include "./gain.glsl.inc"
},
{"glitch.frag",
#include "./glitch.frag.inc"
},
{"inner_glow.frag",
#include "./inner_glow.frag.inc"
},
{"inner_glow.glsl",
#include "./inner_glow.glsl.inc"
},
{"passthru.frag",
#include "./passthru.frag.inc"
},
{"quad.frag",
#include "./quad.frag.inc"
},
{"rgbamatte.frag",
#include "./rgbamatte.frag.inc"
},
{"rounding.glsl",
#include "./rounding.glsl.inc"
},
{"shadow.frag",
#include "./shadow.frag.inc"
},
{"shadow.glsl",
#include "./shadow.glsl.inc"
},
{"surface.frag",
#include "./surface.frag.inc"
},
{"tex300.vert",
#include "./tex300.vert.inc"
},
{"tex320.vert",
#include "./tex320.vert.inc"
},
{"tonemap.glsl",
#include "./tonemap.glsl.inc"
},
};
