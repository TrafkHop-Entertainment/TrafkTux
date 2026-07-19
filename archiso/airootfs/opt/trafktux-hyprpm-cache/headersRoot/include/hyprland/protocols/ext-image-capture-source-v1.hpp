// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// ext_image_capture_source_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2022 Andri Yngvason
    Copyright © 2024 Simon Ser

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


class CExtImageCaptureSourceV1;
class CExtOutputImageCaptureSourceManagerV1;
class CExtImageCaptureSourceV1;
class CWlOutput;
class CExtForeignToplevelImageCaptureSourceManagerV1;
class CExtImageCaptureSourceV1;
class CExtForeignToplevelHandleV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface ext_image_capture_source_v1_interface;
extern const wl_interface ext_output_image_capture_source_manager_v1_interface;
extern const wl_interface ext_foreign_toplevel_image_capture_source_manager_v1_interface;

#endif

struct CExtImageCaptureSourceV1DestroyWrapper {
    wl_listener listener;
    CExtImageCaptureSourceV1* parent = nullptr;
};
            

class CExtImageCaptureSourceV1 {
  public:
    CExtImageCaptureSourceV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtImageCaptureSourceV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtImageCaptureSourceV1*)> &&handler) {
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

    void setDestroy(F<void(CExtImageCaptureSourceV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtImageCaptureSourceV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtImageCaptureSourceV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtImageCaptureSourceV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtOutputImageCaptureSourceManagerV1DestroyWrapper {
    wl_listener listener;
    CExtOutputImageCaptureSourceManagerV1* parent = nullptr;
};
            

class CExtOutputImageCaptureSourceManagerV1 {
  public:
    CExtOutputImageCaptureSourceManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtOutputImageCaptureSourceManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtOutputImageCaptureSourceManagerV1*)> &&handler) {
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

    void setCreateSource(F<void(CExtOutputImageCaptureSourceManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setDestroy(F<void(CExtOutputImageCaptureSourceManagerV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtOutputImageCaptureSourceManagerV1*, uint32_t, wl_resource*)> createSource;
        F<void(CExtOutputImageCaptureSourceManagerV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtOutputImageCaptureSourceManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtOutputImageCaptureSourceManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtForeignToplevelImageCaptureSourceManagerV1DestroyWrapper {
    wl_listener listener;
    CExtForeignToplevelImageCaptureSourceManagerV1* parent = nullptr;
};
            

class CExtForeignToplevelImageCaptureSourceManagerV1 {
  public:
    CExtForeignToplevelImageCaptureSourceManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtForeignToplevelImageCaptureSourceManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtForeignToplevelImageCaptureSourceManagerV1*)> &&handler) {
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

    void setCreateSource(F<void(CExtForeignToplevelImageCaptureSourceManagerV1*, uint32_t, wl_resource*)> &&handler);
    void setDestroy(F<void(CExtForeignToplevelImageCaptureSourceManagerV1*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CExtForeignToplevelImageCaptureSourceManagerV1*, uint32_t, wl_resource*)> createSource;
        F<void(CExtForeignToplevelImageCaptureSourceManagerV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtForeignToplevelImageCaptureSourceManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtForeignToplevelImageCaptureSourceManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
