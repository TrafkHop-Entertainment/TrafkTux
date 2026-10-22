// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// ext_background_effect_v1

/*
 This protocol's authors' copyright notice is:


    Copyright (C) 2015 Martin Gräßlin
    Copyright (C) 2015 Marco Martin
    Copyright (C) 2020 Vlad Zahorodnii
    Copyright (C) 2024 Xaver Hugl

    Permission is hereby granted, free of charge, to any person obtaining a
    copy of this software and associated documentation files (the "Software"),
    to deal in the Software without restriction, including without limitation
    the rights to use, copy, modify, merge, publish, distribute, sublicense,
    and/or sell copies of the Software, and to permit persons to whom the
    Software is furnished to do so, subject to the following conditions:

    The above copyright notice and this permission notice (including the next
    paragraph) shall be included in all copies or substantial portions of the
    Software.

    THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
    IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
    FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.  IN NO EVENT SHALL
    THE AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
    LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
    FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
    DEALINGS IN THE SOFTWARE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;

enum extBackgroundEffectManagerV1Error : uint32_t {
    EXT_BACKGROUND_EFFECT_MANAGER_V1_ERROR_BACKGROUND_EFFECT_EXISTS = 0,
};

enum extBackgroundEffectManagerV1Capability : uint32_t {
    EXT_BACKGROUND_EFFECT_MANAGER_V1_CAPABILITY_BLUR = 1,
};

enum extBackgroundEffectSurfaceV1Error : uint32_t {
    EXT_BACKGROUND_EFFECT_SURFACE_V1_ERROR_SURFACE_DESTROYED = 0,
};


class CExtBackgroundEffectManagerV1;
class CExtBackgroundEffectSurfaceV1;
class CWlSurface;
class CExtBackgroundEffectSurfaceV1;
class CWlRegion;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface ext_background_effect_manager_v1_interface;
extern const wl_interface ext_background_effect_surface_v1_interface;

#endif

struct CExtBackgroundEffectManagerV1DestroyWrapper {
    wl_listener listener;
    CExtBackgroundEffectManagerV1* parent = nullptr;
};
            

class CExtBackgroundEffectManagerV1 {
  public:
    CExtBackgroundEffectManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtBackgroundEffectManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtBackgroundEffectManagerV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CExtBackgroundEffectManagerV1*)> &&handler);
    void setGetBackgroundEffect(F<void(CExtBackgroundEffectManagerV1*, uint32_t, wl_resource*)> &&handler);

    // --------------- Events --------------- //

    void sendCapabilities(extBackgroundEffectManagerV1Capability);
    void sendCapabilitiesRaw(extBackgroundEffectManagerV1Capability);

  private:
    struct {
        F<void(CExtBackgroundEffectManagerV1*)> destroy;
        F<void(CExtBackgroundEffectManagerV1*, uint32_t, wl_resource*)> getBackgroundEffect;
    } requests;

    void onDestroyCalled();

    F<void(CExtBackgroundEffectManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtBackgroundEffectManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtBackgroundEffectSurfaceV1DestroyWrapper {
    wl_listener listener;
    CExtBackgroundEffectSurfaceV1* parent = nullptr;
};
            

class CExtBackgroundEffectSurfaceV1 {
  public:
    CExtBackgroundEffectSurfaceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtBackgroundEffectSurfaceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtBackgroundEffectSurfaceV1*)> &&handler) {
        onDestroy = std::move(handler);
    }

    // set the data for this resource
    void setData(void* data) {
        pData = data;
    }

    // get the data for this resource
    void* data() {
        return pData;
    }

    // get the raw wl_resource ptr
    wl_resource* resource() {
        return pResource;
    }

    // get the client
    wl_client* client() {
        return wl_resource_get_client(pResource);
    }

    // send an error
    void error(uint32_t error, const std::string& message) {
        wl_resource_post_error(pResource, error, "%s", message.c_str());
    }

    // send out of memory
    void noMemory() {
        wl_resource_post_no_memory(pResource);
    }

    // get the resource version
    int version() {
        return wl_resource_get_version(pResource);
    }
            
    // --------------- Requests --------------- //

    void setDestroy(F<void(CExtBackgroundEffectSurfaceV1*)> &&handler);
    void setSetBlurRegion(F<void(CExtBackgroundEffectSurfaceV1*, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtBackgroundEffectSurfaceV1*)> destroy;
        F<void(CExtBackgroundEffectSurfaceV1*, wl_resource*)> setBlurRegion;
    } requests;

    void onDestroyCalled();

    F<void(CExtBackgroundEffectSurfaceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtBackgroundEffectSurfaceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
