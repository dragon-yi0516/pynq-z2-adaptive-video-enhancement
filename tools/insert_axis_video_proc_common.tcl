# =============================================================================
# ai_video 公共“把自定义 IP 插进 BD”脚本（阶段 1/2/3/6/7 共用）
#
# 各阶段目录里的 tcl/insert_*.tcl 只是调用本脚本的一行入口。
# 这样“怎么改接视频流、挂哪路 AXI-Lite、地址怎么分配”只有一份实现。
# =============================================================================

namespace eval ai_video {

    # -------------------------------------------------------------------------
    # 定位 Vivado 工程的输出目录（不用你 cd，也不用挪文件）
    #   本文件在  <工程根>/tools/ 下
    #   <工程根>            = 上一级
    #   Vivado 输出目录      = <工程根>/../bitstream
    # 如果以后你把 bitstream 放到别处，设个环境变量即可：
    #   export AI_VIDEO_BITSTREAM_DIR=/path/to/bitstream
    # -------------------------------------------------------------------------
    variable tools_dir [file normalize [file dirname [info script]]]
    variable root_dir  [file normalize [file join $tools_dir ..]]
    variable _bs_dir   [file normalize [file join $root_dir .. bitstream]]

    proc bitstream_dir {} {
        variable _bs_dir
        if {[info exists ::env(AI_VIDEO_BITSTREAM_DIR)]} {
            return [file normalize $::env(AI_VIDEO_BITSTREAM_DIR)]
        }
        return $_bs_dir
    }

    # -------------------------------------------------------------------------
    # 打开工程之前，先看看它是不是已经开着了。
    #
    # 为什么需要：阶段 1 的顺序是“先 source cv_ov5640.tcl 建底板、再插 IP”，
    # 底板脚本跑完时这个工程本来就是打开的。这时候再 open_project 同一个工程，
    # Vivado 2024.2 会直接报：
    #     ERROR: [Coretcl 2-101] Project '...' is already open.
    # 2018.3 上不会报，2024.2 上必报，所以这里统一包一层。
    # -------------------------------------------------------------------------
    proc open_project_if_needed {xpr} {
        set want [file normalize $xpr]
        set cur ""
        catch { set cur [current_project -quiet] }
        if {$cur ne ""} {
            set curfile ""
            catch { set curfile [get_property FILE_NAME $cur] }
            if {$curfile ne "" && [file normalize $curfile] eq $want} {
                puts "  (工程已经打开，跳过 open_project)"
                return
            }
            puts "  (先关闭当前已打开的工程：$curfile)"
            close_project
        }
        open_project $want
    }

    # -------------------------------------------------------------------------
    # 关掉当前打开的 Block Design（如果有）。
    # 同上：底板脚本 cv_ov5640.tcl 跑完时 BD 是开着的，2024.2 里再 open_bd_design
    # 同一个 BD 会报重复打开。底板在 cv_ov5640.tcl 结尾已经 save_bd_design 过，
    # 所以这里直接关是安全的。
    # -------------------------------------------------------------------------
    proc close_open_bd {} {
        set bd ""
        catch { set bd [current_bd_design -quiet] }
        if {$bd ne ""} {
            set n ""
            catch { set n [get_property NAME $bd] }
            puts "  (先关闭已打开的 Block Design $n)"
            catch { close_bd_design $bd }
        }
    }

    # -------------------------------------------------------------------------
    # 在 BD 的 cell 上按名字（大小写不敏感）找接口针脚。
    #
    # 为什么需要：IP 打包器会把 HDL 里的 s_axi_* 端口推断成一个叫 s_axi 的接口
    # （小写），BD 里生成的针脚名就是 s_axi。脚本里如果硬写 S_AXI 就会找不到，
    # 报的是很难懂的 “pin not found”。这里统一做大小写不敏感查找。
    # -------------------------------------------------------------------------
    proc intf_pin {cell name} {
        set p [get_bd_intf_pins -quiet ${cell}/${name}]
        if {[llength $p] > 0} { return [lindex $p 0] }
        foreach q [get_bd_intf_pins -quiet ${cell}/*] {
            set n ""
            catch { set n [get_property NAME $q] }
            if {[string tolower $n] eq [string tolower $name]} { return $q }
        }
        puts "ERROR: 在 $cell 上找不到接口 $name。该 cell 实际的接口针脚："
        foreach q [get_bd_intf_pins -quiet ${cell}/*] {
            puts "    [get_property NAME $q]"
        }
        error "在 $cell 上找不到接口 $name"
    }

    # -------------------------------------------------------------------------
    # 只在目标针脚还没接线时才 connect_bd_net。
    #
    # 为什么需要：有些线在重跑阶段时是“还在”的。
    # 最典型的是 ps7_0_axi_periph 的 M05_ACLK / M05_ARESETN：
    # 阶段 2 把它们接到了 FCLK_CLK0 / 复位；阶段 3 删掉 IP 单元并不会拆掉这两根线，
    # 再 connect_bd_net 一次就会报：
    #     WARNING: [BD 41-395] all ports/pins are already connected to ...
    #     ERROR:   [BD 5-4] Error: running connect_bd_net.
    # -------------------------------------------------------------------------
    proc connect_if_open {dst src} {
        set nets [get_bd_nets -quiet -of_objects $dst]
        if {[llength $nets] > 0} {
            puts "  (已连接，跳过) $dst"
            return
        }
        connect_bd_net $src $dst
    }

    # -------------------------------------------------------------------------
    # insert_proc -vlnv <user.org:user:axis_video_proc:1.2>
    #             -ip_repo <dir> [-overlay cv_ov5640] [-design cv_ov5640]
    #             [-with_axi_lite 1] [-axi_mi_index 5]
    #             [-extra_ports {pin...}] [-extra_conns {...}]
    # -------------------------------------------------------------------------
    proc insert_proc {args} {
        array set opt {
            -vlnv           ""
            -ip_repo        ""
            -overlay        cv_ov5640
            -design         cv_ov5640
            -with_axi_lite  1
            -axi_mi_index   5
        }
        foreach {k v} $args {
            if {![info exists opt($k)]} { error "未知参数 $k" }
            set opt($k) $v
        }
        if {$opt(-vlnv) eq "" || $opt(-ip_repo) eq ""} {
            error "insert_proc 需要 -vlnv 和 -ip_repo"
        }
        set ip_repo [file normalize $opt(-ip_repo)]
        set ov      $opt(-overlay)
        set bs      [bitstream_dir]

        puts "== ai_video::insert_proc =="
        puts "  VLNV   : $opt(-vlnv)"
        puts "  IP repo: $ip_repo"
        puts "  BD 目录: $bs"

        if {![file exists [file join $bs ${ov}.tcl]]} {
            error "在 $bs 里找不到 ${ov}.tcl。\n\
请确认目录结构是：\n\
    <某个父目录>/bitstream/          <- Vivado 工程（cv_ov5640.tcl 在这里）\n\
    <某个父目录>/ai_video/tools/     <- 本脚本在这里\n\
或者设环境变量 AI_VIDEO_BITSTREAM_DIR 指向 bitstream 目录。"
        }

        open_project_if_needed [file join $bs ${ov} ${ov}.xpr]

        # 顺手把已经不存在的旧路径剔掉：前几个阶段的 ip_repo 如果被删过，
        # 工程里会留一条失效路径，每次打开都报一堆 WARNING，容易把真错误淹掉。
        set keep {}
        foreach p [get_property ip_repo_paths [current_project]] {
            set pn [file normalize $p]
            if {[file exists $pn]} { lappend keep $pn }
        }
        if {[lsearch -exact $keep $ip_repo] < 0} { lappend keep $ip_repo }
        set_property ip_repo_paths $keep [current_project]
        update_ip_catalog -rebuild
        close_open_bd
        open_bd_design [file join $bs ${ov} "${ov}.srcs" sources_1 bd ${ov} "${ov}.bd"]

        # 幂等：先删掉旧实例。
        # 连 mlp_engine_0 / mlp_rst_inv 一起删，是为了支持“从阶段 6/7 退回到阶段 1/2/3”：
        # 旧版本的 axis_video_proc 没有 mlp_* 端口，如果留着 mlp_engine 和它的连线，
        # 删掉 IP 之后那几根线会悬空，validate_bd_design 会直接报错。
        foreach cell {axis_video_proc_0 mlp_engine_0 mlp_rst_inv} {
            set old [get_bd_cells -quiet $cell]
            if {[llength $old] > 0} {
                puts "  删除已存在的 $cell"
                delete_bd_objs $old
            }
        }

        create_bd_cell -type ip -vlnv $opt(-vlnv) axis_video_proc_0

        # ---- 视频通路：demosaic -> IP -> VDMA0 ----
        set old_net [get_bd_intf_nets -quiet v_demosaic_0_m_axis_video]
        if {[llength $old_net] > 0} {
            delete_bd_objs $old_net
        }
        connect_bd_intf_net -intf_net v_demosaic_0_m_axis_video \
            [get_bd_intf_pins v_demosaic_0/m_axis_video] \
            [get_bd_intf_pins axis_video_proc_0/s_axis_video]
        connect_bd_intf_net -intf_net axis_video_proc_0_m_axis_video \
            [get_bd_intf_pins axis_video_proc_0/m_axis_video] \
            [get_bd_intf_pins axi_vdma_0/S_AXIS_S2MM]

        # ---- 时钟 / 复位 ----
        connect_if_open [get_bd_pins axis_video_proc_0/aclk] \
            [get_bd_pins processing_system7_0/FCLK_CLK0]
        connect_if_open [get_bd_pins axis_video_proc_0/aresetn] \
            [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]

        # ---- AXI-Lite ----
        if {$opt(-with_axi_lite)} {
            set idx $opt(-axi_mi_index)
            set need [expr {$idx + 1}]
            set mi [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
            if {$mi < $need} {
                set_property CONFIG.NUM_MI $need [get_bd_cells ps7_0_axi_periph]
            }
            set mi_name [format "M%02d" $idx]
            connect_bd_intf_net -intf_net ps7_0_axi_periph_${mi_name}_AXI \
                [get_bd_intf_pins ps7_0_axi_periph/${mi_name}_AXI] \
                [intf_pin axis_video_proc_0 S_AXI]
            connect_if_open [get_bd_pins ps7_0_axi_periph/${mi_name}_ACLK] \
                [get_bd_pins processing_system7_0/FCLK_CLK0]
            connect_if_open [get_bd_pins ps7_0_axi_periph/${mi_name}_ARESETN] \
                [get_bd_pins rst_ps7_0_100M/peripheral_aresetn]
        } else {
            # 不带 AXI-Lite 的阶段（比如从阶段 3 退回到阶段 1）：
            # 把互联里多出来的那一路主口收回去，否则会留一个悬空的 M0x_AXI，
            # validate_bd_design 会直接报错。
            set idx $opt(-axi_mi_index)
            set mi  [get_property CONFIG.NUM_MI [get_bd_cells ps7_0_axi_periph]]
            if {$mi > $idx} {
                puts "  收窄 ps7_0_axi_periph 的 NUM_MI: $mi -> $idx"
                set_property CONFIG.NUM_MI $idx [get_bd_cells ps7_0_axi_periph]
            }
        }

        assign_bd_address

        # 兜底：万一 IP 里还是带了自动生成的 reg0 地址块，BD 里就会多一个地址段，
        # PYNQ 解析 .hwh 时可能挑错基地址。这里直接把这个多余的段删掉。
        catch {
            foreach _s [get_bd_addr_segs -quiet -of_objects [get_bd_cells axis_video_proc_0]] {
                set _sn [get_property NAME $_s]
                if {[string tolower [lindex [split $_sn /] end]] eq "reg0"} {
                    puts "  删除多余的地址段 $_sn"
                    delete_bd_objs $_s
                }
            }
        }

        validate_bd_design
        save_bd_design

        if {$opt(-with_axi_lite)} {
            # 地址段名字跟着接口名走（可能是 s_axi/Reg 也可能是 S_AXI/Reg），
            # 所以不硬编码，直接把该 cell 下的地址段都列出来。
            catch {
                foreach s [get_bd_addr_segs -quiet -of_objects [get_bd_cells axis_video_proc_0]] {
                    puts "  地址段 [get_property NAME $s] 基地址 = [get_property offset $s]"
                }
            }
        }
        close_bd_design [current_bd_design]
        puts "== 插入完成 =="
    }
}
