# =============================================================================
# ai_video 公共 IP 打包脚本（阶段 1/2/3/6/7 共用）
#
# 为什么抽成一个公共脚本：
#   这几个阶段打包的是同一个 IP，只是 HDL 内容不同。如果每个阶段各抄一份打包
#   脚本，很容易出现“这次 tuser 连了、下次忘了”这种接口漂移，导致 BD 里
#   前后两版 IP 的接口不一样，问题非常难查。这里只维护一份接口定义。
#
# 每个阶段目录里的 tcl/package_ip.tcl 只是调用本脚本的一行入口。
#
# 踩过的两个坑（都写在对应代码的注释里，别再改回去）：
#   1. ASSOCIATED_BUSIF / POLARITY / TDATA_NUM_BYTES 这类是 **bus parameter**，
#      必须 ipx::add_bus_parameter 建出来再 set_property value；
#      直接 set_property 到 bus interface 上会报 Unknown property。
#   2. ipx::package_project 会自动推断接口，而且推断出来的**名字大小写**
#      可能和我们想的不一样（S_AXI 会被推成 s_axi）。
#      所以下面所有地方都按“大小写不敏感”去找接口，绝不硬编码大小写。
# =============================================================================

namespace eval ai_video {

    proc _lower {s} { return [string tolower $s] }

    # -------------------------------------------------------------------------
    # 拿到（必要时新建）一个 bus interface。
    # 先按原名找、再按全小写/全大写找、最后把所有接口列出来做大小写不敏感匹配；
    # 都找不到才新建。这样无论打包器推断出 s_axi 还是 S_AXI 都能正确复用，
    # 不会出现“建了个同名不同大小写的重复接口”。
    # -------------------------------------------------------------------------
    proc ensure_busif {core name} {
        foreach cand [list $name [_lower $name] [string toupper $name]] {
            set bi [ipx::get_bus_interfaces $cand -of_objects $core -quiet]
            if {[llength $bi] > 0} { return [lindex $bi 0] }
        }
        foreach existing [ipx::get_bus_interfaces -of_objects $core -quiet] {
            set en ""
            catch { set en [get_property name $existing] }
            if {[_lower $en] eq [_lower $name]} { return $existing }
        }
        ipx::add_bus_interface $name $core
        set bi [ipx::get_bus_interfaces $name -of_objects $core -quiet]
        if {[llength $bi] == 0} {
            error "无法在 IP 里创建 bus interface $name"
        }
        return [lindex $bi 0]
    }

    # 取接口的“真实名字”（后面拼 ASSOCIATED_BUSIF、内存映射名字都要用它）
    proc busif_name {bi} {
        set n ""
        catch { set n [get_property name $bi] }
        return $n
    }

    proc ensure_portmap {bi logical physical} {
        set pm [ipx::get_port_maps $logical -of_objects $bi -quiet]
        if {[llength $pm] == 0} {
            ipx::add_port_map $logical $bi
            set pm [ipx::get_port_maps $logical -of_objects $bi -quiet]
        }
        if {[llength $pm] == 0} {
            error "无法在接口 [busif_name $bi] 上建立端口映射 $logical"
        }
        set_property physical_name $physical [lindex $pm 0]
    }

    # -------------------------------------------------------------------------
    # 设置 bus interface 上的“接口参数”
    #
    # ASSOCIATED_BUSIF / ASSOCIATED_RESET / POLARITY / TDATA_NUM_BYTES /
    # HAS_TUSER / HAS_TLAST / PROTOCOL / DATA_WIDTH / ADDR_WIDTH
    # 这些**不是** bus interface 的直接属性，而是挂在它下面的 bus parameter。
    #
    # 直接写：
    #     set_property ASSOCIATED_BUSIF {s_axis_video:m_axis_video} $aclk
    # 在 Vivado 2024.2 会报：
    #     Unknown property 'ASSOCIATED_BUSIF' on bus_interface
    #
    # 正确写法是先 ipx::add_bus_parameter 建出参数对象，再 set_property value。
    # -------------------------------------------------------------------------
    proc set_bus_param {bi param value} {
        set bp [ipx::get_bus_parameters $param -of_objects $bi -quiet]
        if {[llength $bp] == 0} {
            if {[catch { ipx::add_bus_parameter $param $bi } err]} {
                puts "  (提示) 接口 [busif_name $bi] 不支持参数 $param，已跳过"
                return ""
            }
            set bp [ipx::get_bus_parameters $param -of_objects $bi -quiet]
        }
        if {[llength $bp] == 0} { return "" }
        set_property value $value [lindex $bp 0]
        return [lindex $bp 0]
    }

    # -------------------------------------------------------------------------
    # 只在 interface_mode 还是空的时候才设置。
    # 打包器已经按端口名（s_axis_*/m_axis_*/aclk/aresetn/s_axi_*）推断出正确方向，
    # 再覆盖只会帮倒忙。
    # -------------------------------------------------------------------------
    proc ensure_mode {bi mode} {
        set cur ""
        catch { set cur [get_property interface_mode $bi] }
        if {$cur eq ""} {
            set_property interface_mode $mode $bi
        }
    }

    # -------------------------------------------------------------------------
    # 配一个 AXIS 接口。
    # 注意：物理端口名固定按 s_axis_video_* / m_axis_video_* 拼，
    # 和接口的“逻辑名字”无关 —— 因为 HDL 里的端口名是固定的。
    # 返回接口的真实名字，供 ASSOCIATED_BUSIF 使用。
    # -------------------------------------------------------------------------
    proc setup_axis {core busif pfx mode} {
        set bi [ensure_busif $core $busif]
        set bn [busif_name $bi]
        if {$bn eq ""} { set bn $busif }

        set_property bus_type_vlnv         xilinx.com:interface:axis:1.0     $bi
        set_property abstraction_type_vlnv xilinx.com:interface:axis_rtl:1.0 $bi
        ensure_mode $bi $mode

        # 物理端口名固定按 HDL 里的前缀拼（s_axis_video_* / m_axis_video_*），
        # 和接口的逻辑名字无关，避免大小写差异把物理名拼错。
        ensure_portmap $bi TDATA  ${pfx}_tdata
        ensure_portmap $bi TVALID ${pfx}_tvalid
        ensure_portmap $bi TREADY ${pfx}_tready
        ensure_portmap $bi TUSER  ${pfx}_tuser
        ensure_portmap $bi TLAST  ${pfx}_tlast

        set_bus_param $bi TDATA_NUM_BYTES 3
        set_bus_param $bi HAS_TUSER 1
        set_bus_param $bi HAS_TLAST 1
        return $bn
    }

    # -------------------------------------------------------------------------
    # package_ip -hdl <file> -ip_repo <dir> [-tmp <dir>] [-version 1.0]
    #            [-with_axi_lite 0|1] [-part xc7z020clg400-1]
    # -------------------------------------------------------------------------
    proc package_ip {args} {
        array set opt {
            -hdl            ""
            -ip_repo        ""
            -tmp            ""
            -vendor         user.org
            -library        user
            -name           axis_video_proc
            -version        1.0
            -part           xc7z020clg400-1
            -with_axi_lite  0
        }
        foreach {k v} $args {
            if {![info exists opt($k)]} { error "未知参数 $k" }
            set opt($k) $v
        }
        if {$opt(-hdl) eq "" || $opt(-ip_repo) eq ""} {
            error "package_ip 需要 -hdl 和 -ip_repo"
        }
        set hdl     [file normalize $opt(-hdl)]
        set ip_repo [file normalize $opt(-ip_repo)]
        if {$opt(-tmp) eq ""} {
            set tmp [file normalize [file join $ip_repo .. _ip_pkg_tmp]]
        } else {
            set tmp [file normalize $opt(-tmp)]
        }

        if {![file exists $hdl]} { error "找不到 HDL: $hdl" }
        file mkdir $ip_repo
        file mkdir $tmp

        # 清掉上一次打包的残留。
        # 为什么要清：ipx::package_project 一上来就会写出 component.xml，
        # 如果上一次跑到一半失败，IP 目录里会留一个接口不完整的半成品；
        # 不清掉的话下一次可能出现“IP 在但接口不对”的怪问题。
        # 只删我们自己这个 VLNV 的目录，且必须确认它在 $ip_repo 下面。
        set out_dir [file join $ip_repo "${opt(-vendor)}_${opt(-library)}_${opt(-name)}_${opt(-version)}"]
        if {[file exists $out_dir]} {
            set a [file normalize $ip_repo]
            set b [file normalize $out_dir]
            if {[string first $a $b] == 0} {
                puts "  清理上次打包残留: $out_dir"
                file delete -force $out_dir
            }
        }

        puts "== ai_video::package_ip =="
        puts "  HDL     : $hdl"
        puts "  IP repo : $ip_repo"
        puts "  VLNV    : $opt(-vendor):$opt(-library):$opt(-name):$opt(-version)"
        puts "  AXI-Lite: $opt(-with_axi_lite)"

        create_project -force ip_pkg_tmp $tmp -part $opt(-part)
        add_files -norecurse $hdl
        set_property top $opt(-name) [current_fileset]
        update_compile_order -fileset sources_1

        ipx::package_project -root_dir $ip_repo -vendor $opt(-vendor) -library $opt(-library) -taxonomy /UserIP -import_files
        set core [ipx::current_core]

        set_property name         $opt(-name)    $core
        set_property version      $opt(-version) $core
        set_property display_name "Axis Video Proc" $core
        set_property description "OV5640 AXI4-Stream video processing IP (ai_video, v$opt(-version))" $core
        # vendor_display_name 在个别小版本上不存在，设不上也不影响功能
        catch { set_property vendor_display_name "ai_video" $core }

        # ---- 时钟 aclk ------------------------------------------------------
        # 注意 bus_type 是 ...:clock:1.0，abstraction 才是 ...:clock_rtl:1.0
        set aclk [ensure_busif $core aclk]
        set_property bus_type_vlnv         xilinx.com:signal:clock:1.0     $aclk
        set_property abstraction_type_vlnv xilinx.com:signal:clock_rtl:1.0 $aclk
        ensure_mode $aclk master
        ensure_portmap $aclk CLK aclk

        # ---- 复位 aresetn ---------------------------------------------------
        set arst [ensure_busif $core aresetn]
        set_property bus_type_vlnv         xilinx.com:signal:reset:1.0     $arst
        set_property abstraction_type_vlnv xilinx.com:signal:reset_rtl:1.0 $arst
        ensure_mode $arst slave
        set_bus_param $arst POLARITY ACTIVE_LOW
        ensure_portmap $arst RST aresetn

        # ---- 两个 AXIS ------------------------------------------------------
        set s_name [setup_axis $core s_axis_video s_axis_video slave]
        set m_name [setup_axis $core m_axis_video m_axis_video master]

        # ---- AXI-Lite（可选）------------------------------------------------
        set assoc "$s_name:$m_name"
        if {$opt(-with_axi_lite)} {
            set axi      [ensure_busif $core S_AXI]
            set axi_name [busif_name $axi]
            if {$axi_name eq ""} { set axi_name "s_axi" }
            puts "  AXI-Lite 接口实际名字: $axi_name"

            set_property bus_type_vlnv         xilinx.com:interface:aximm:1.0     $axi
            set_property abstraction_type_vlnv xilinx.com:interface:aximm_rtl:1.0 $axi
            ensure_mode $axi slave

            # 这几个同样是 bus parameter（注意是大写名字）
            set_bus_param $axi PROTOCOL   AXI4LITE
            set_bus_param $axi DATA_WIDTH 32
            set_bus_param $axi ADDR_WIDTH 6

            # 物理端口名固定是 s_axi_*（HDL 里就是这么写的）
            ensure_portmap $axi AWADDR  s_axi_awaddr
            ensure_portmap $axi AWVALID s_axi_awvalid
            ensure_portmap $axi AWREADY s_axi_awready
            ensure_portmap $axi WDATA   s_axi_wdata
            ensure_portmap $axi WSTRB   s_axi_wstrb
            ensure_portmap $axi WVALID  s_axi_wvalid
            ensure_portmap $axi WREADY  s_axi_wready
            ensure_portmap $axi BRESP   s_axi_bresp
            ensure_portmap $axi BVALID  s_axi_bvalid
            ensure_portmap $axi BREADY  s_axi_bready
            ensure_portmap $axi ARADDR  s_axi_araddr
            ensure_portmap $axi ARVALID s_axi_arvalid
            ensure_portmap $axi ARREADY s_axi_arready
            ensure_portmap $axi RDATA   s_axi_rdata
            ensure_portmap $axi RRESP   s_axi_rresp
            ensure_portmap $axi RVALID  s_axi_rvalid
            ensure_portmap $axi RREADY  s_axi_rready

            # 内存映射：没有它，BD 里给 IP 分配不了地址，notebook 也读写不了。
            # 名字必须和接口名一致（BD 里的段名就是 IP/内存映射名/地址块名）。
            set mm [ipx::get_memory_maps $axi_name -of_objects $core -quiet]
            if {[llength $mm] == 0} {
                ipx::add_memory_map $axi_name $core
                set mm [ipx::get_memory_maps $axi_name -of_objects $core -quiet]
            }
            set ab [ipx::get_address_blocks Reg -of_objects $mm -quiet]
            if {[llength $ab] == 0} {
                ipx::add_address_block Reg $mm
                set ab [ipx::get_address_blocks Reg -of_objects $mm -quiet]
            }
            set_property range 64 [lindex $ab 0]
            catch { set_property usage register [lindex $ab 0] }
            catch { set_property slave_memory_map_ref $axi_name $axi }

            # 2024.2 新增的坑：ipx::package_project 会自动给 AXI-Lite 生成一个
            # 默认地址块（名字叫 reg0），和我们上面手工建的 Reg 重复。
            # 结果 BD 里会出现两个地址段：
            #   /axis_video_proc_0/s_axi/Reg   -> 0x43C1_0000 (64K)  ← 我们要的
            #   /axis_video_proc_0/s_axi/reg0  -> 0x4000_0000 (4K)   ← 多余的
            # 多出来的那一段会让 PYNQ 解析 .hwh 时挑错基地址，寄存器全读不对，
            # 所以这里把它删掉，只留 Reg。
            foreach _m $mm {
                foreach _a [ipx::get_address_blocks -of_objects $_m -quiet] {
                    set _an ""
                    catch { set _an [get_property name $_a] }
                    if {$_an ne "" && $_an ne "Reg"} {
                        puts "  删除自动生成的重复地址块: $_an"
                        if {[catch { ipx::remove_address_block $_an $_m } _err]} {
                            puts "  (警告) 删除地址块 $_an 失败：$_err"
                            puts "         该 IP 在 BD 里会多出一个地址段；插 BD 时脚本会再兜一次底。"
                        }
                    }
                }
            }

            append assoc ":" $axi_name
        }

        # ASSOCIATED_BUSIF 必须用接口的“真实名字”拼接，否则 BD 不认
        set_bus_param $aclk ASSOCIATED_BUSIF  $assoc
        set arst_name [busif_name $arst]
        if {$arst_name eq ""} { set arst_name "aresetn" }
        set_bus_param $aclk ASSOCIATED_RESET  $arst_name

        # ---- 收尾 -----------------------------------------------------------
        # 本 IP 没有任何可配置的 IP 参数（GUI），create_xgui_files 在某些版本上会
        # 因为“没有参数可生成”而报错，所以这里失败就跳过，不影响功能。
        catch { ipx::create_xgui_files $core }
        ipx::update_checksums $core
        catch { ipx::check_integrity -quiet $core }
        ipx::save_core $core
        close_project

        set out "$ip_repo/${opt(-vendor)}_${opt(-library)}_${opt(-name)}_${opt(-version)}/component.xml"
        puts "== 打包完成: $out =="
        return $out
    }
}
