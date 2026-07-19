// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// hyprland_toplevel_mapping_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2025 WhySoBad
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


class CHyprlandToplevelMappingManagerV1;
class CHyprlandToplevelWindowMappingHandleV1;
class CExtForeignToplevelHandleV1;
class CHyprlandToplevelWindowMappingHandleV1;
class CZwlrForeignToplevelHandleV1;
class CHyprlandToplevelWindowMappingHandleV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface hyprland_toplevel_mapping_manager_v1_interface;
extern const wl_interface hyprland_toplevel_window_mapping_handle_v1_interface;

#endif

struct CHyprlandToplevelMappingManagerV1DestroyWrapper {
    wl_listener listener;
    CHyprlandToplevelMappingManagerV1* parent = nullptr;
};
            

class CHyprlandToplevelMappingManagerV1 {
  public:
    CHyprlandToplevelMappingManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CHyprlandToplevelMappingManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CHyprlandToplevelMappingManagerV1*)> &&handler) {
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

    void setGetWindowForToplevel(F<void(CHyprlandToplevelMappingManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setGetWindowForToplevelWlr(F<void(CHyprlandToplevelMappingManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setDestroy(F<void(CHyprlandToplevelMappingManagerV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CHyprlandToplevelMappingManagerV1*, uint32_t, wl_resource*)> getWindowForToplevel;
        F<void(CHyprlandToplevelMappingManagerV1*, uint32_t, wl_resource*)> getWindowForToplevelWlr;
        F<void(CHyprlandToplevelMappingManagerV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CHyprlandToplevelMappingManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CHyprlandToplevelMappingManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CHyprlandToplevelWindowMappingHandleV1DestroyWrapper {
    wl_listener listener;
    CHyprlandToplevelWindowMappingHandleV1* parent = nullptr;
};
            

class CHyprlandToplevelWindowMappingHandleV1 {
  public:
    CHyprlandToplevelWindowMappingHandleV1(wl_client* client, uint32_t version, uint32_t id);
    ~CHyprlandToplevelWindowMappingHandleV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CHyprlandToplevelWindowMappingHandleV1*)> &&handler) {
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

    void setDestroy(F<void(CHyprlandToplevelWindowMappingHandleV1*)> &&handler);

    // --------------- Events --------------- //

    void sendWindowAddress(uint32_t, uint32_t);
    void sendFailed();
    void sendWindowAddressRaw(uint32_t, uint32_t);
    void sendFailedRaw();

  private:
    struct {
        F<void(CHyprlandToplevelWindowMappingHandleV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CHyprlandToplevelWindowMappingHandleV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CHyprlandToplevelWindowMappingHandleV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
