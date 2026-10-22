// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// hyprland_input_capture_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2025 Fl0w

    All rights reserved.

    Redistribution and use in source and binary forms, with or without
    modification, are permitted provided that the following conditions are met:

    1. Redistributions of source code must retain the above copyright notice, this
    list of conditions and the following disclaimer.

    2. Redistributions in binary form must reproduce the above copyright notice,
    this list of conditions and the following disclaimer in the documentation
    and/or other materials provided with the distribution.

    3. Neither the name of the copyright holder nor the names of its
    contributors may be used to endorse or promote products derived from
    this software without specific prior written permission.

    THIS SOFTWARE IS PROVIDED BY THE COPYRIGHT HOLDERS AND CONTRIBUTORS "AS IS"
    AND ANY EXPRESS OR IMPLIED WARRANTIES, INCLUDING, BUT NOT LIMITED TO, THE
    IMPLIED WARRANTIES OF MERCHANTABILITY AND FITNESS FOR A PARTICULAR PURPOSE ARE
    DISCLAIMED. IN NO EVENT SHALL THE COPYRIGHT HOLDER OR CONTRIBUTORS BE LIABLE
    FOR ANY DIRECT, INDIRECT, INCIDENTAL, SPECIAL, EXEMPLARY, OR CONSEQUENTIAL
    DAMAGES (INCLUDING, BUT NOT LIMITED TO, PROCUREMENT OF SUBSTITUTE GOODS OR
    SERVICES; LOSS OF USE, DATA, OR PROFITS; OR BUSINESS INTERRUPTION) HOWEVER
    CAUSED AND ON ANY THEORY OF LIABILITY, WHETHER IN CONTRACT, STRICT LIABILITY,
    OR TORT (INCLUDING NEGLIGENCE OR OTHERWISE) ARISING IN ANY WAY OUT OF THE USE
    OF THIS SOFTWARE, EVEN IF ADVISED OF THE POSSIBILITY OF SUCH DAMAGE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;

enum hyprlandInputCaptureV1Error : uint32_t {
    HYPRLAND_INPUT_CAPTURE_V1_ERROR_INVALID_BARRIER_ID = 0,
    HYPRLAND_INPUT_CAPTURE_V1_ERROR_INVALID_BARRIER = 1,
    HYPRLAND_INPUT_CAPTURE_V1_ERROR_INVALID_ACTIVATION_ID = 2,
};


class CHyprlandInputCaptureManagerV1;
class CHyprlandInputCaptureV1;
class CHyprlandInputCaptureV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface hyprland_input_capture_manager_v1_interface;
extern const wl_interface hyprland_input_capture_v1_interface;

#endif

struct CHyprlandInputCaptureManagerV1DestroyWrapper {
    wl_listener listener;
    CHyprlandInputCaptureManagerV1* parent = nullptr;
};
            

class CHyprlandInputCaptureManagerV1 {
  public:
    CHyprlandInputCaptureManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CHyprlandInputCaptureManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CHyprlandInputCaptureManagerV1*)> &&handler) {
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

    void setCreateSession(F<void(CHyprlandInputCaptureManagerV1*, uint32_t, const char*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CHyprlandInputCaptureManagerV1*, uint32_t, const char*)> createSession;
    } requests;

    void onDestroyCalled();

    F<void(CHyprlandInputCaptureManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CHyprlandInputCaptureManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CHyprlandInputCaptureV1DestroyWrapper {
    wl_listener listener;
    CHyprlandInputCaptureV1* parent = nullptr;
};
            

class CHyprlandInputCaptureV1 {
  public:
    CHyprlandInputCaptureV1(wl_client* client, uint32_t version, uint32_t id);
    ~CHyprlandInputCaptureV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CHyprlandInputCaptureV1*)> &&handler) {
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

    void setClearBarriers(F<void(CHyprlandInputCaptureV1*)> &&handler);
    void setAddBarrier(F<void(CHyprlandInputCaptureV1*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t)> &&handler);
    void setEnable(F<void(CHyprlandInputCaptureV1*)> &&handler);
    void setDisable(F<void(CHyprlandInputCaptureV1*)> &&handler);
    void setRelease(F<void(CHyprlandInputCaptureV1*, uint32_t, wl_fixed_t, wl_fixed_t)> &&handler);

    // --------------- Events --------------- //

    void sendEisFd(int32_t);
    void sendDisabled();
    void sendActivated(uint32_t, wl_fixed_t, wl_fixed_t, uint32_t);
    void sendDeactivated(uint32_t);
    void sendEisFdRaw(int32_t);
    void sendDisabledRaw();
    void sendActivatedRaw(uint32_t, wl_fixed_t, wl_fixed_t, uint32_t);
    void sendDeactivatedRaw(uint32_t);

  private:
    struct {
        F<void(CHyprlandInputCaptureV1*)> clearBarriers;
        F<void(CHyprlandInputCaptureV1*, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t, uint32_t)> addBarrier;
        F<void(CHyprlandInputCaptureV1*)> enable;
        F<void(CHyprlandInputCaptureV1*)> disable;
        F<void(CHyprlandInputCaptureV1*, uint32_t, wl_fixed_t, wl_fixed_t)> release;
    } requests;

    void onDestroyCalled();

    F<void(CHyprlandInputCaptureV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CHyprlandInputCaptureV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
