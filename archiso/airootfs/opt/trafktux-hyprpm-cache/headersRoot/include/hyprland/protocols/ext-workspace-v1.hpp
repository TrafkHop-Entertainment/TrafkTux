// Generated with hyprwayland-scanner 0.4.6. Made with vaxry's keyboard and ❤️.
// ext_workspace_v1

/*
 This protocol's authors' copyright notice is:


    Copyright © 2019 Christopher Billington
    Copyright © 2020 Ilia Bozhinov
    Copyright © 2022 Victoria Brekenfeld

    Permission to use, copy, modify, distribute, and sell this
    software and its documentation for any purpose is hereby granted
    without fee, provided that the above copyright notice appear in
    all copies and that both that copyright notice and this permission
    notice appear in supporting documentation, and that the name of
    the copyright holders not be used in advertising or publicity
    pertaining to distribution of the software without specific,
    written prior permission.  The copyright holders make no
    representations about the suitability of this software for any
    purpose.  It is provided "as is" without express or implied
    warranty.

    THE COPYRIGHT HOLDERS DISCLAIM ALL WARRANTIES WITH REGARD TO THIS
    SOFTWARE, INCLUDING ALL IMPLIED WARRANTIES OF MERCHANTABILITY AND
    FITNESS, IN NO EVENT SHALL THE COPYRIGHT HOLDERS BE LIABLE FOR ANY
    SPECIAL, INDIRECT OR CONSEQUENTIAL DAMAGES OR ANY DAMAGES
    WHATSOEVER RESULTING FROM LOSS OF USE, DATA OR PROFITS, WHETHER IN
    AN ACTION OF CONTRACT, NEGLIGENCE OR OTHER TORTIOUS ACTION,
    ARISING OUT OF OR IN CONNECTION WITH THE USE OR PERFORMANCE OF
    THIS SOFTWARE.
  
*/

#pragma once

#include <functional>
#include <cstdint>
#include <string>
#include <wayland-server.h>

#define F std::function

struct wl_client;
struct wl_resource;

enum extWorkspaceGroupHandleV1GroupCapabilities : uint32_t {
    EXT_WORKSPACE_GROUP_HANDLE_V1_GROUP_CAPABILITIES_CREATE_WORKSPACE = 1,
};

enum extWorkspaceHandleV1State : uint32_t {
    EXT_WORKSPACE_HANDLE_V1_STATE_ACTIVE = 1,
    EXT_WORKSPACE_HANDLE_V1_STATE_URGENT = 2,
    EXT_WORKSPACE_HANDLE_V1_STATE_HIDDEN = 4,
};

enum extWorkspaceHandleV1WorkspaceCapabilities : uint32_t {
    EXT_WORKSPACE_HANDLE_V1_WORKSPACE_CAPABILITIES_ACTIVATE = 1,
    EXT_WORKSPACE_HANDLE_V1_WORKSPACE_CAPABILITIES_DEACTIVATE = 2,
    EXT_WORKSPACE_HANDLE_V1_WORKSPACE_CAPABILITIES_REMOVE = 4,
    EXT_WORKSPACE_HANDLE_V1_WORKSPACE_CAPABILITIES_ASSIGN = 8,
};


class CExtWorkspaceManagerV1;
class CExtWorkspaceGroupHandleV1;
class CExtWorkspaceHandleV1;
class CExtWorkspaceGroupHandleV1;
class CWlOutput;
class CWlOutput;
class CExtWorkspaceHandleV1;
class CExtWorkspaceHandleV1;
class CExtWorkspaceHandleV1;
class CExtWorkspaceGroupHandleV1;

#ifndef HYPRWAYLAND_SCANNER_NO_INTERFACES
extern const wl_interface ext_workspace_manager_v1_interface;
extern const wl_interface ext_workspace_group_handle_v1_interface;
extern const wl_interface ext_workspace_handle_v1_interface;

#endif

struct CExtWorkspaceManagerV1DestroyWrapper {
    wl_listener listener;
    CExtWorkspaceManagerV1* parent = nullptr;
};
            

class CExtWorkspaceManagerV1 {
  public:
    CExtWorkspaceManagerV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtWorkspaceManagerV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtWorkspaceManagerV1*)> &&handler) {
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

    void setCommit(F<void(CExtWorkspaceManagerV1*)> &&handler);
    void setStop(F<void(CExtWorkspaceManagerV1*)> &&handler);

    // --------------- Events --------------- //

    void sendWorkspaceGroup(CExtWorkspaceGroupHandleV1*);
    void sendWorkspace(CExtWorkspaceHandleV1*);
    void sendDone();
    void sendFinished();
    void sendWorkspaceGroupRaw(CExtWorkspaceGroupHandleV1*);
    void sendWorkspaceRaw(CExtWorkspaceHandleV1*);
    void sendDoneRaw();
    void sendFinishedRaw();

  private:
    struct {
        F<void(CExtWorkspaceManagerV1*)> commit;
        F<void(CExtWorkspaceManagerV1*)> stop;
    } requests;

    void onDestroyCalled();

    F<void(CExtWorkspaceManagerV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtWorkspaceManagerV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtWorkspaceGroupHandleV1DestroyWrapper {
    wl_listener listener;
    CExtWorkspaceGroupHandleV1* parent = nullptr;
};
            

class CExtWorkspaceGroupHandleV1 {
  public:
    CExtWorkspaceGroupHandleV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtWorkspaceGroupHandleV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtWorkspaceGroupHandleV1*)> &&handler) {
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

    void setCreateWorkspace(F<void(CExtWorkspaceGroupHandleV1*, const char*)> &&handler);
    void setDestroy(F<void(CExtWorkspaceGroupHandleV1*)> &&handler);

    // --------------- Events --------------- //

    void sendCapabilities(extWorkspaceGroupHandleV1GroupCapabilities);
    void sendOutputEnter(wl_resource*);
    void sendOutputLeave(wl_resource*);
    void sendWorkspaceEnter(CExtWorkspaceHandleV1*);
    void sendWorkspaceLeave(CExtWorkspaceHandleV1*);
    void sendRemoved();
    void sendCapabilitiesRaw(extWorkspaceGroupHandleV1GroupCapabilities);
    void sendOutputEnterRaw(wl_resource*);
    void sendOutputLeaveRaw(wl_resource*);
    void sendWorkspaceEnterRaw(wl_resource*);
    void sendWorkspaceLeaveRaw(wl_resource*);
    void sendRemovedRaw();

  private:
    struct {
        F<void(CExtWorkspaceGroupHandleV1*, const char*)> createWorkspace;
        F<void(CExtWorkspaceGroupHandleV1*)> destroy;
    } requests;

    void onDestroyCalled();

    F<void(CExtWorkspaceGroupHandleV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtWorkspaceGroupHandleV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};


struct CExtWorkspaceHandleV1DestroyWrapper {
    wl_listener listener;
    CExtWorkspaceHandleV1* parent = nullptr;
};
            

class CExtWorkspaceHandleV1 {
  public:
    CExtWorkspaceHandleV1(wl_client* client, uint32_t version, uint32_t id);
    ~CExtWorkspaceHandleV1();


    // set a listener for when this resource is _being_ destroyed
    void setOnDestroy(F<void(CExtWorkspaceHandleV1*)> &&handler) {
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

    void setDestroy(F<void(CExtWorkspaceHandleV1*)> &&handler);
    void setActivate(F<void(CExtWorkspaceHandleV1*)> &&handler);
    void setDeactivate(F<void(CExtWorkspaceHandleV1*)> &&handler);
    void setAssign(F<void(CExtWorkspaceHandleV1*, wl_resource*)> &&handler);
    void setRemove(F<void(CExtWorkspaceHandleV1*)> &&handler);

    // --------------- Events --------------- //

    void sendId(const char*);
    void sendName(const char*);
    void sendCoordinates(wl_array*);
    void sendState(extWorkspaceHandleV1State);
    void sendCapabilities(extWorkspaceHandleV1WorkspaceCapabilities);
    void sendRemoved();
    void sendIdRaw(const char*);
    void sendNameRaw(const char*);
    void sendCoordinatesRaw(wl_array*);
    void sendStateRaw(extWorkspaceHandleV1State);
    void sendCapabilitiesRaw(extWorkspaceHandleV1WorkspaceCapabilities);
    void sendRemovedRaw();

  private:
    struct {
        F<void(CExtWorkspaceHandleV1*)> destroy;
        F<void(CExtWorkspaceHandleV1*)> activate;
        F<void(CExtWorkspaceHandleV1*)> deactivate;
        F<void(CExtWorkspaceHandleV1*, wl_resource*)> assign;
        F<void(CExtWorkspaceHandleV1*)> remove;
    } requests;

    void onDestroyCalled();

    F<void(CExtWorkspaceHandleV1*)> onDestroy;

    wl_resource* pResource = nullptr;

    CExtWorkspaceHandleV1DestroyWrapper resourceDestroyListener;

    void* pData = nullptr;
};



#undef F
