// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// fifo_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2023 Valve Corporation

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

enum wpFifoManagerV1Error : uint32_t {
    WP_FIFO_MANAGER_V1_ERROR_ALREADY_EXISTS = 0,
};

enum wpFifoV1Error : uint32_t {
    WP_FIFO_V1_ERROR_SURFACE_DESTROYED = 0,
};


class CWpFifoManagerV1;
class CWpFifoV1;
class CWlSurface;
class CWpFifoV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface wp_fifo_manager_v1_interface;
extern const wl_interface wp_fifo_v1_interface;

#endif

struct CWpFifoManagerV1DestroyWrapper {
    wl_listener listener;
    CWpFifoManagerV1* parent = nullptr;
};
            

class CWpFifoManagerV1 {
  public:
    CWpFifoManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpFifoManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpFifoManagerV1*)> &&handler) {
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

    void setDestroy(F<void(CWpFifoManagerV1*)> &&handler);
    void setGetFifo(F<void(CWpFifoManagerV1*, uint32_t, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpFifoManagerV1*)> destroy;
        F<void(CWpFifoManagerV1*, uint32_t, wl_resource*)> getFifo;
    } requests;

    void onDestroyCalled();

    F<void(CWpFifoManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpFifoManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CWpFifoV1DestroyWrapper {
    wl_listener listener;
    CWpFifoV1* parent = nullptr;
};
            

class CWpFifoV1 {
  public:
    CWpFifoV1(wl_client* client, uint32_t version, uint32_t id);
    ~CWpFifoV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CWpFifoV1*)> &&handler) {
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

    void setSetBarrier(F<void(CWpFifoV1*)> &&handler);
    void setWaitBarrier(F<void(CWpFifoV1*)> &&handler);
    void setDestroy(F<void(CWpFifoV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CWpFifoV1*)> setBarrier;
        F<void(CWpFifoV1*)> waitBarrier;
        F<void(CWpFifoV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CWpFifoV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CWpFifoV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
