// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// xdg_system_bell_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2016, 2023 Red Hat

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


class CXdgSystemBellV1;
class CWlSurface;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface xdg_system_bell_v1_interface;

#endif

struct CXdgSystemBellV1DestroyWrapper {
    wl_listener listener;
    CXdgSystemBellV1* parent = nullptr;
};
            

class CXdgSystemBellV1 {
  public:
    CXdgSystemBellV1(wl_client* client, uint32_t version, uint32_t id);
    ~CXdgSystemBellV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CXdgSystemBellV1*)> &&handler) {
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

    void setDestroy(F<void(CXdgSystemBellV1*)> &&handler);
    void setRing(F<void(CXdgSystemBellV1*, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CXdgSystemBellV1*)> destroy;
        F<void(CXdgSystemBellV1*, wl_resource*)> ring;
    } requests;

    void onDestroyCalled();

    F<void(CXdgSystemBellV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CXdgSystemBellV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
