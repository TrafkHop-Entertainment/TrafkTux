// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// xdg_foreign_unstable_v2

/*
 This protocol's authors' copyright notice is:


    Copyright © 2015-2016 Red Hat Inc.

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

enum zxdgExporterV2Error : uint32_t {
    ZXDG_EXPORTER_V2_ERROR_INVALID_SURFACE = 0,
};

enum zxdgImportedV2Error : uint32_t {
    ZXDG_IMPORTED_V2_ERROR_INVALID_SURFACE = 0,
};


class CZxdgExporterV2;
class CZxdgExportedV2;
class CWlSurface;
class CZxdgImporterV2;
class CZxdgImportedV2;
class CZxdgExportedV2;
class CZxdgImportedV2;
class CWlSurface;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface zxdg_exporter_v2_interface;
extern const wl_interface zxdg_importer_v2_interface;
extern const wl_interface zxdg_exported_v2_interface;
extern const wl_interface zxdg_imported_v2_interface;

#endif

struct CZxdgExporterV2DestroyWrapper {
    wl_listener listener;
    CZxdgExporterV2* parent = nullptr;
};
            

class CZxdgExporterV2 {
  public:
    CZxdgExporterV2(wl_client* client, uint32_t version, uint32_t id);
    ~CZxdgExporterV2();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZxdgExporterV2*)> &&handler) {
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

    void setDestroy(F<void(CZxdgExporterV2*)> &&handler);
    void setExportToplevel(F<void(CZxdgExporterV2*, uint32_t, wl_resource*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CZxdgExporterV2*)> destroy;
        F<void(CZxdgExporterV2*, uint32_t, wl_resource*)> exportToplevel;
    } requests;

    void onDestroyCalled();

    F<void(CZxdgExporterV2*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZxdgExporterV2DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZxdgImporterV2DestroyWrapper {
    wl_listener listener;
    CZxdgImporterV2* parent = nullptr;
};
            

class CZxdgImporterV2 {
  public:
    CZxdgImporterV2(wl_client* client, uint32_t version, uint32_t id);
    ~CZxdgImporterV2();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZxdgImporterV2*)> &&handler) {
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

    void setDestroy(F<void(CZxdgImporterV2*)> &&handler);
    void setImportToplevel(F<void(CZxdgImporterV2*, uint32_t, const char*)> &&handler);

    // --------------- Events --------------- //


  private:
    struct {
        F<void(CZxdgImporterV2*)> destroy;
        F<void(CZxdgImporterV2*, uint32_t, const char*)> importToplevel;
    } requests;

    void onDestroyCalled();

    F<void(CZxdgImporterV2*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZxdgImporterV2DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZxdgExportedV2DestroyWrapper {
    wl_listener listener;
    CZxdgExportedV2* parent = nullptr;
};
            

class CZxdgExportedV2 {
  public:
    CZxdgExportedV2(wl_client* client, uint32_t version, uint32_t id);
    ~CZxdgExportedV2();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZxdgExportedV2*)> &&handler) {
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

    void setDestroy(F<void(CZxdgExportedV2*)> &&handler);

    // --------------- Events --------------- //

    void sendHandle(const char*);
    void sendHandleRaw(const char*);

  private:
    struct {
        F<void(CZxdgExportedV2*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CZxdgExportedV2*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZxdgExportedV2DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CZxdgImportedV2DestroyWrapper {
    wl_listener listener;
    CZxdgImportedV2* parent = nullptr;
};
            

class CZxdgImportedV2 {
  public:
    CZxdgImportedV2(wl_client* client, uint32_t version, uint32_t id);
    ~CZxdgImportedV2();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CZxdgImportedV2*)> &&handler) {
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

    void setDestroy(F<void(CZxdgImportedV2*)> &&handler);
    void setSetParentOf(F<void(CZxdgImportedV2*, wl_resource*)> &&handler);

    // --------------- Events --------------- //

    void sendDestroyed();
    void sendDestroyedRaw();

  private:
    struct {
        F<void(CZxdgImportedV2*)> destroy;
        F<void(CZxdgImportedV2*, wl_resource*)> setParentOf;
    } requests;

    void onDestroyCalled();

    F<void(CZxdgImportedV2*)> onDestroy;

    wl_resource* pResource = nullptr;

    CZxdgImportedV2DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
